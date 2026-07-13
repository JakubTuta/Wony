import argparse
import csv
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def get_latest_log_files(logs_dir: Path) -> Tuple[Path, Path]:
    """Get the most recent log and CSV files"""
    log_files = list(logs_dir.glob("ai_assistant_*.log"))
    csv_files = list(logs_dir.glob("ai_assistant_*.csv"))

    if not log_files or not csv_files:
        raise FileNotFoundError("No log files found in the logs directory")

    latest_log = max(log_files, key=lambda f: f.stat().st_mtime)
    latest_csv = max(csv_files, key=lambda f: f.stat().st_mtime)

    return latest_log, latest_csv


def analyze_user_interactions(csv_file: Path) -> Dict:
    """Analyze user interaction patterns from CSV logs"""
    interactions = {
        "total_inputs": 0,
        "text_inputs": 0,
        "speech_inputs": 0,
        "functions_called": Counter(),
        "input_timeline": [],
        "response_times": [],
    }

    with open(csv_file, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            log_name = row["Log Name"]
            timestamp = row["Timestamp"]
            user_input = row["User Input"]
            function_called = row["Function Called"]

            if log_name == "user_input_text":
                interactions["total_inputs"] += 1
                interactions["text_inputs"] += 1
                interactions["input_timeline"].append((timestamp, "text", user_input))
            elif log_name == "user_input_speech":
                interactions["total_inputs"] += 1
                interactions["speech_inputs"] += 1
                interactions["input_timeline"].append((timestamp, "speech", user_input))
            elif log_name == "function_called" and function_called:
                interactions["functions_called"][function_called] += 1

    return interactions


def analyze_function_usage(csv_file: Path) -> Dict[str, Dict[str, Any]]:
    """Analyze function call patterns"""
    function_stats: Dict[str, Dict[str, Any]] = defaultdict(
        lambda: {"calls": 0, "success": 0, "errors": 0, "responses": []}
    )

    with open(csv_file, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            log_name = row["Log Name"]
            function_called = row["Function Called"]
            function_response = row["Function Response"]

            if log_name == "function_called" and function_called:
                function_stats[function_called]["calls"] += 1
            elif log_name == "function_response" and function_called:
                function_stats[function_called]["success"] += 1
                if function_response:
                    function_stats[function_called]["responses"].append(
                        function_response[:100]
                    )
            elif log_name == "error" and function_called:
                function_stats[function_called]["errors"] += 1

    return dict(function_stats)


def analyze_errors(csv_file: Path) -> List[Dict]:
    """Analyze error patterns"""
    errors = []

    with open(csv_file, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row["Log Name"] == "error":
                errors.append(
                    {
                        "timestamp": row["Timestamp"],
                        "context": row["Function Called"],
                        "message": row["Function Response"],
                    }
                )

    return errors


def generate_summary_report(logs_dir: Optional[Path] = None) -> str:
    """Generate a comprehensive summary report"""
    if logs_dir is None:
        logs_dir = Path("logs")

    if not logs_dir.exists():
        return "No logs directory found. Run the AI Assistant first to generate logs."

    try:
        latest_log, latest_csv = get_latest_log_files(logs_dir)
    except FileNotFoundError as e:
        return str(e)

    # Analyze the data
    interactions = analyze_user_interactions(latest_csv)
    functions = analyze_function_usage(latest_csv)
    errors = analyze_errors(latest_csv)

    # Generate report
    report = []
    report.append("=" * 60)
    report.append("AI ASSISTANT LOG ANALYSIS REPORT")
    report.append("=" * 60)
    report.append(f"Analysis of: {latest_csv.name}")
    report.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    report.append("")

    # User Interaction Summary
    report.append("USER INTERACTION SUMMARY")
    report.append("-" * 30)
    report.append(f"Total User Inputs: {interactions['total_inputs']}")
    report.append(f"  - Text Inputs: {interactions['text_inputs']}")
    report.append(f"  - Speech Inputs: {interactions['speech_inputs']}")

    if interactions["total_inputs"] > 0:
        text_percentage = (
            interactions["text_inputs"] / interactions["total_inputs"]
        ) * 100
        speech_percentage = (
            interactions["speech_inputs"] / interactions["total_inputs"]
        ) * 100
        report.append(
            f"  - Text: {text_percentage:.1f}%, Speech: {speech_percentage:.1f}%"
        )
    report.append("")

    # Function Usage Summary
    report.append("FUNCTION USAGE SUMMARY")
    report.append("-" * 30)
    if functions:
        report.append("Most Called Functions:")
        for func, stats in sorted(
            functions.items(), key=lambda x: x[1]["calls"], reverse=True
        )[:10]:
            success_rate = (
                (stats["success"] / stats["calls"] * 100) if stats["calls"] > 0 else 0
            )
            report.append(
                f"  - {func}: {stats['calls']} calls, {success_rate:.1f}% success rate"
            )
    else:
        report.append("No function calls recorded.")
    report.append("")

    # Error Summary
    report.append("ERROR SUMMARY")
    report.append("-" * 30)
    if errors:
        report.append(f"Total Errors: {len(errors)}")
        error_contexts = Counter(
            error["context"] for error in errors if error["context"]
        )
        if error_contexts:
            report.append("Errors by Context:")
            for context, count in error_contexts.most_common(5):
                report.append(f"  - {context}: {count} errors")

        report.append("\nRecent Errors:")
        for error in errors[-5:]:  # Last 5 errors
            report.append(f"  - {error['timestamp']}: {error['message'][:50]}...")
    else:
        report.append("No errors recorded.")
    report.append("")

    # Recent Activity
    report.append("RECENT ACTIVITY")
    report.append("-" * 30)
    if interactions["input_timeline"]:
        report.append("Last 5 User Inputs:")
        for timestamp, input_type, user_input in interactions["input_timeline"][-5:]:
            report.append(f"  - {timestamp} ({input_type}): {user_input[:50]}...")
    report.append("")

    report.append("=" * 60)

    return "\n".join(report)


def main():
    parser = argparse.ArgumentParser(description="Analyze AI Assistant logs")
    parser.add_argument(
        "--logs-dir",
        "-d",
        type=str,
        default="logs",
        help="Path to logs directory (default: logs)",
    )
    parser.add_argument(
        "--output", "-o", type=str, help="Save report to file instead of printing"
    )

    args = parser.parse_args()

    logs_dir = Path(args.logs_dir)
    report = generate_summary_report(logs_dir)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(report)
        print(f"Report saved to: {args.output}")
    else:
        print(report)


if __name__ == "__main__":
    main()
