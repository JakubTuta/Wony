import csv
import io
import logging
import typing
from datetime import datetime
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent


class CSVFormatter(logging.Formatter):
    """Custom formatter for CSV logging"""

    def __init__(self):
        super().__init__()

    def format(self, record):
        # Extract custom fields from the record
        timestamp = datetime.fromtimestamp(record.created).strftime(
            "%Y-%m-%d %H:%M:%S.%f"
        )[:-3]
        log_name = getattr(record, "log_name", "general")
        user_input = getattr(record, "user_input", "")
        function_called = getattr(record, "function_called", "")
        function_response = getattr(record, "function_response", "")

        # csv.writer, not an f-string: replies are routinely multi-line, and an
        # embedded newline splits one record across rows.
        buffer = io.StringIO()
        writer = csv.writer(buffer, quoting=csv.QUOTE_ALL, lineterminator="")
        writer.writerow(
            [timestamp, log_name, user_input, function_called, function_response]
        )
        return buffer.getvalue()


class Logger:
    """
    Centralized logging system for the AI Assistant project.

    Handles both regular log files and CSV files with structured data including:
    - Full timestamp for each log entry
    - Custom names for log entries (user input, function called, etc.)
    - User input tracking (text or speech)
    - Function/method call tracking
    - Function response logging
    """

    _instance = None
    _initialized = False

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(Logger, cls).__new__(cls)
        return cls._instance

    def __init__(self):
        if not self._initialized:
            self._setup_logging()
            Logger._initialized = True

    def _setup_logging(self):
        """Initialize the logging system with both regular and CSV loggers"""

        # Create logs directory if it doesn't exist. Anchored to the repo root
        # (not the process CWD) so tray mode (launched by Task Scheduler,
        # which may set a different working directory) still writes here.
        logs_dir = self.get_logs_directory()
        logs_dir.mkdir(exist_ok=True)

        # Generate timestamp for log files
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        # Setup regular logger
        self.logger = logging.getLogger("ai_assistant")
        self.logger.setLevel(logging.INFO)

        # Remove existing handlers to avoid duplication
        self.logger.handlers.clear()

        # Regular log file handler
        log_file = logs_dir / f"ai_assistant_{timestamp}.log"
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_formatter = logging.Formatter(
            "%(asctime)s | %(levelname)s | %(name)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        file_handler.setFormatter(file_formatter)
        self.logger.addHandler(file_handler)

        # Setup CSV logger
        self.csv_logger = logging.getLogger("ai_assistant_csv")
        self.csv_logger.setLevel(logging.INFO)
        self.csv_logger.handlers.clear()

        # CSV file handler
        csv_file = logs_dir / f"ai_assistant_{timestamp}.csv"
        csv_handler = logging.FileHandler(csv_file, encoding="utf-8")
        csv_handler.setFormatter(CSVFormatter())
        self.csv_logger.addHandler(csv_handler)

        # Write CSV header
        with open(csv_file, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(
                [
                    "Timestamp",
                    "Log Name",
                    "User Input",
                    "Function Called",
                    "Function Response",
                ]
            )

        self.logger.info("Logging system initialized")
        self._log_csv(
            "system",
            "",
            "logging_system_initialized",
            "Logging system successfully started",
        )

    def log_user_input(self, user_input: str, input_type: str = "text"):
        """
        Log user input (text or speech)

        Args:
            user_input: The user's input text
            input_type: Type of input ('text' or 'speech')
        """
        log_name = f"user_input_{input_type}"
        message = f"User input ({input_type}): {user_input}"

        self.logger.info(message)
        self._log_csv(log_name, user_input, "", "")

    def log_function_call(
        self,
        function_name: str,
        user_input: str = "",
        args: typing.Optional[typing.Dict] = None,
    ):
        """
        Log when a function/method is called

        Args:
            function_name: Name of the function being called
            user_input: The original user input that triggered this function
            args: Function arguments (optional)
        """
        log_name = "function_called"
        args_str = f" with args: {args}" if args else ""
        message = f"Function called: {function_name}{args_str}"

        self.logger.info(message)
        self._log_csv(log_name, user_input, function_name, "")

    def log_function_response(
        self, function_name: str, response: str, user_input: str = ""
    ):
        """
        Log the response from a called function

        Args:
            function_name: Name of the function that returned the response
            response: The function's response
            user_input: The original user input (optional)
        """
        log_name = "function_response"
        message = f"Response from {function_name}: {response}"

        self.logger.info(message)
        self._log_csv(log_name, user_input, function_name, response)

    def log_error(self, error_message: str, context: str = ""):
        """
        Log error messages

        Args:
            error_message: The error message
            context: Additional context about where the error occurred
        """
        log_name = "error"
        full_message = (
            f"ERROR in {context}: {error_message}"
            if context
            else f"ERROR: {error_message}"
        )

        self.logger.error(full_message)
        self._log_csv(log_name, "", context, error_message)

    def log_system_event(self, event: str, details: str = ""):
        """
        Log system events (startup, shutdown, configuration changes, etc.)

        Args:
            event: The system event name
            details: Additional details about the event
        """
        log_name = "system_event"
        message = f"System event: {event}"
        if details:
            message += f" - {details}"

        self.logger.info(message)
        self._log_csv(log_name, "", event, details)

    def log_custom(
        self,
        log_name: str,
        message: str,
        user_input: str = "",
        function_called: str = "",
        function_response: str = "",
    ):
        """
        Log custom events with full control over all fields

        Args:
            log_name: Custom name for the log entry
            message: Log message for the regular log file
            user_input: User input field for CSV
            function_called: Function called field for CSV
            function_response: Function response field for CSV
        """
        self.logger.info(f"{log_name}: {message}")
        self._log_csv(log_name, user_input, function_called, function_response)

    def _log_csv(
        self,
        log_name: str,
        user_input: str,
        function_called: str,
        function_response: str,
    ):
        """
        Internal method to log to CSV file

        Args:
            log_name: Name/category of the log entry
            user_input: User input text
            function_called: Name of function that was called
            function_response: Response from the function
        """
        # Create a log record with custom attributes
        record = self.csv_logger.makeRecord(
            name=self.csv_logger.name,
            level=logging.INFO,
            fn="",
            lno=0,
            msg="",
            args=(),
            exc_info=None,
        )

        # Raw values — CSVFormatter quotes and escapes them via csv.writer.
        record.log_name = log_name
        record.user_input = user_input or ""
        record.function_called = function_called
        record.function_response = function_response or ""

        self.csv_logger.handle(record)

    def get_logs_directory(self) -> Path:
        """Get the logs directory path (anchored to the repo root)"""
        return _REPO_ROOT / "logs"

    def cleanup_old_logs(self, days_to_keep: int = 30):
        """
        Clean up log files older than specified days

        Args:
            days_to_keep: Number of days to keep log files (default: 30)
        """
        logs_dir = self.get_logs_directory()
        cutoff_time = datetime.now().timestamp() - (days_to_keep * 24 * 60 * 60)

        deleted_count = 0
        for log_file in logs_dir.glob("ai_assistant_*.log"):
            if log_file.stat().st_mtime < cutoff_time:
                log_file.unlink()
                deleted_count += 1

        for csv_file in logs_dir.glob("ai_assistant_*.csv"):
            if csv_file.stat().st_mtime < cutoff_time:
                csv_file.unlink()
                deleted_count += 1

        if deleted_count > 0:
            self.log_system_event(
                "log_cleanup", f"Deleted {deleted_count} old log files"
            )


# Singleton instance
logger = Logger()
