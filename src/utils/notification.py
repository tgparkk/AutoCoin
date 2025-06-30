from __future__ import annotations
import asyncio
from queue import Empty, Queue
from threading import Event

from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    AIORateLimiter,
)

from config.api_config import TELEGRAM_CHAT_ID, TELEGRAM_TOKEN
from src.utils.logger import get_logger

logger = get_logger(__name__)


class TelegramBot:
    """python-telegram-bot v20 Dispatcher 기반 알림 및 명령 처리"""

    POLL_INTERVAL = 0.5  # 초 – 노티 큐 폴링 간격

    @staticmethod
    def run(command_q: Queue, notify_q: Queue, stop_event: Event) -> None:  # pragma: no cover – 별도 프로세스
        """별도 프로세스에서 호출

        Parameters
        ----------
        command_q : Queue
            Trader 등으로 전달되는 명령 큐 (dict)
        notify_q : Queue
            시스템 전역 알림 문자열 큐
        stop_event : Event
            전체 시스템 shutdown 이벤트
        """

        if TELEGRAM_TOKEN is None or TELEGRAM_CHAT_ID is None:
            logger.warning("Telegram 비활성화: 토큰 또는 챗 ID 미설정")
            stop_event.wait()
            return

        async def _notification_job(context: ContextTypes.DEFAULT_TYPE) -> None:  # noqa: D401
            """JobQueue 에 의해 주기적으로 실행 – notify_q 소비"""
            try:
                # 여러 개의 메시지를 한 번에 소모하기 위해 루프 사용
                while True:
                    msg = notify_q.get_nowait()
                    await context.bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=str(msg))
            except Empty:
                # 전송할 메시지가 없는 경우
                pass

        # ------------------------- Command Handlers -------------------------
        async def _pause(update, context):  # type: ignore[override]
            command_q.put({"type": "pause"})
            await update.message.reply_text("⏸ 매매 일시정지 요청이 접수되었습니다.")

        async def _resume(update, context):  # type: ignore[override]
            command_q.put({"type": "resume"})
            await update.message.reply_text("▶️ 매매 재개 요청이 접수되었습니다.")

        async def _balance(update, context):  # type: ignore[override]
            command_q.put({"type": "portfolio_status"})
            await update.message.reply_text("💰 잔고 조회 요청 완료.")

        async def _positions(update, context):  # type: ignore[override]
            command_q.put({"type": "strategy_performance"})
            await update.message.reply_text("📊 포지션·성과 조회 요청 완료.")

        async def _shutdown(update, context):  # type: ignore[override]
            await update.message.reply_text("📴 봇 종료 요청을 처리합니다. 잠시만 기다려 주세요.")
            command_q.put({"type": "shutdown"})
            stop_event.set()
            # 애플리케이션 종료
            await context.application.stop()
            await context.application.shutdown()

        async def _help(update, context):  # type: ignore[override]
            help_text = (
                "/pause – 매매 일시정지\n"
                "/resume – 매매 재개\n"
                "/balance – 잔고 조회\n"
                "/positions – 포지션/성과 조회\n"
                "/shutdown – 봇 완전 종료"
            )
            await update.message.reply_text(help_text)

        async def _run() -> None:
            # 기본 ApplicationBuilder
            builder = ApplicationBuilder().token(TELEGRAM_TOKEN)

            # AIORateLimiter 가 정상적으로 초기화되는 경우에만 적용한다.
            try:
                rate_limiter = AIORateLimiter()
                builder = builder.rate_limiter(rate_limiter)
            except Exception as exc:  # pylint: disable=broad-except
                # aiolimiter 미설치·버전 불일치 등 어떤 이유든 레이트 리미터 없이 계속 진행
                logger.warning(
                    "AIORateLimiter 비활성화: %s – 레이트 리미터 없이 실행합니다.",
                    exc,
                )
                builder = builder.rate_limiter(None)  # 자동 생성 방지

            application = builder.build()

            # 명령 핸들러 등록
            application.add_handler(CommandHandler("pause", _pause))
            application.add_handler(CommandHandler("resume", _resume))
            application.add_handler(CommandHandler("balance", _balance))
            application.add_handler(CommandHandler("positions", _positions))
            application.add_handler(CommandHandler("shutdown", _shutdown))
            application.add_handler(CommandHandler("help", _help))

            # JobQueue – 알림 전송
            if application.job_queue:
                application.job_queue.run_repeating(
                    _notification_job, interval=TelegramBot.POLL_INTERVAL
                )
            else:
                logger.warning(
                    "JobQueue 미사용 – python-telegram-bot[job-queue] 미설치"
                )

            # stop_event 가 set 될 때까지 대기한 후, 애플리케이션을 정지시킨다.
            async def _monitor_stop():
                while not stop_event.is_set():
                    await asyncio.sleep(0.5)
                if application.running:
                    await application.stop()

            # Application 이 실제로 실행(drive)된 후에 백그라운드 태스크를 등록해야 PTB 경고가 발생하지 않는다.
            logger.info("TelegramBot 시작 – 챗 ID=%s", TELEGRAM_CHAT_ID)

            # ------------------ PTB life-cycle 수동 제어 ------------------
            async with application:
                await application.start()

                # stop_event 를 감시하는 태스크는 *start 이후*에 등록한다.
                application.create_task(_monitor_stop())

                if application.updater:
                    # Telegram Polling 시작
                    await application.updater.start_polling()
                    # idle() 대신 stop_event 를 주기적으로 확인하며 대기
                    while not stop_event.is_set():
                        await asyncio.sleep(0.5)
                else:
                    # Updater 가 없으면 stop_event 대기
                    while not stop_event.is_set():
                        await asyncio.sleep(0.5)

            # async with 블록을 벗어나면 initialize/stop/shutdown 이 자동으로 처리된다.

        # ------------------------------- run -------------------------------
        try:
            asyncio.run(_run())
        except Exception as exc:  # pragma: no cover
            logger.exception("TelegramBot 종료 – 예외 발생: %s", exc) 