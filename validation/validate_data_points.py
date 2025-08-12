import argparse
print(f"DEBUG: Executing script: {__file__}")
import json
import os
import subprocess
import sys
import tempfile
import shutil
from pathlib import Path

from swebench.harness.run_evaluation import main as run_evaluation_main

def validate_data_point(data_point_path: Path, timeout: int):
    """
    Validates a single data point.
    """
    print(f"Validating data point: {data_point_path}")

    try:
        with open(data_point_path, "r") as f:
            data_point = json.load(f)
    except json.JSONDecodeError:
        print(f"Error: Invalid JSON in {data_point_path}")
        return False
    except FileNotFoundError:
        print(f"Error: File not found: {data_point_path}")
        return False

    # For fail cases, we need to handle the case where the instance_id doesn't exist in the dataset
    # Determine fail case by the filename, not the instance_id
    is_fail_case = data_point_path.name.endswith("-fail.json")

    config_path = Path(__file__).parent / "config.json"
    with open(config_path, "r") as f:
        config = json.load(f)
    required_fields = config["required_fields"]

    for field in required_fields:
        if field not in data_point:
            print(f"Error: Missing required field '{field}' in {data_point_path}")
            return False

    # Run evaluation after patch
    print("Running evaluation after patch...")

    log_root = Path("logs")
    if log_root.exists():
        print(f"DEBUG: Contents of {log_root.absolute()}:")
        for p in log_root.iterdir():
            print(f"  - {p.name}")
    else:
        print(f"DEBUG: {log_root.absolute()} does not exist.")

    # For fail cases, we need to use the base instance_id (without -fail suffix)
    # because the fail instance_id doesn't exist in the dataset
    if is_fail_case:
        base_instance_id = data_point["instance_id"].replace("-fail", "")
        print(f"Fail case detected: using base instance_id: {base_instance_id}")
    else:
        base_instance_id = data_point["instance_id"]

    # Clean up previous log directory for this validation run to ensure a fresh start
    run_id_after = f"validation_{data_point['instance_id']}_after"
    log_dir = Path("logs") / run_id_after
    if log_dir.exists():
        print(f"Removing existing log directory: {log_dir}")
        shutil.rmtree(log_dir)

    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".jsonl") as pred_file:
        prediction = {
            "model_name_or_path": "golden",
            "instance_id": base_instance_id,  # Используем базовый ID для поиска в датасете
            "model_patch": data_point["patch"],
        }
        pred_file.write(json.dumps(prediction))
        predictions_path_after = pred_file.name
    
    try:
        run_evaluation_main(
            dataset_name="SWE-bench/SWE-bench",
            split="test",
            instance_ids=[base_instance_id],
            predictions_path=predictions_path_after,
            max_workers=1,
            force_rebuild=True,
            cache_level="instance",
            clean=True,
            open_file_limit=4096,
            run_id=run_id_after,
            timeout=timeout,
            namespace=None,
            rewrite_reports=False,
            modal=False,
            validate=None,
            instance_image_tag="latest",
            report_dir=".",
        )
    except ValueError as e:
        print(f"Error during evaluation: {e}")
        return False
    finally:
        os.remove(predictions_path_after)

    # The detailed report is in the logs directory, not in the root
    report_path_after = Path("logs") / "run_evaluation" / run_id_after / "golden" / base_instance_id / "report.json"
    if not report_path_after.exists():
        print(f"Error: Evaluation report not found for {base_instance_id} (after patch)")
        print(f"Expected path: {report_path_after}")
        return False
    with open(report_path_after, "r") as f:
        report_after = json.load(f)
    
    # Extract passed tests from the new report format
    tests_passed_after = set()
    
    # The report has the instance_id as the top-level key
    instance_report = report_after.get(base_instance_id, {})
    tests_status = instance_report.get("tests_status", {})
    
    # Collect all successful tests from all categories
    for category, results in tests_status.items():
        if "success" in results:
            tests_passed_after.update(results["success"])

    fail_to_pass = set(json.loads(data_point["FAIL_TO_PASS"]))
    pass_to_pass = set(json.loads(data_point["PASS_TO_PASS"]))

    if is_fail_case:
        # For fail cases, we expect FAIL_TO_PASS tests to NOT pass after the patch
        # and PASS_TO_PASS tests to still pass
        failed_fail_to_pass = fail_to_pass - tests_passed_after
        if not failed_fail_to_pass:
            print(f"Error: FAIL_TO_PASS tests should have failed after the patch, but they all passed: {fail_to_pass}")
            return False
        
        missing_pass_to_pass = pass_to_pass - tests_passed_after
        if missing_pass_to_pass:
            print(f"Error: The following PASS_TO_PASS tests did not pass after the patch: {missing_pass_to_pass}")
            return False
        
        print(f"Successfully validated fail case: {data_point_path}")
        print(f"FAIL_TO_PASS tests that correctly failed: {sorted(failed_fail_to_pass)}")
        return True
    else:
        # For normal cases, we expect all tests to pass
        missing_fail_to_pass = fail_to_pass - tests_passed_after
        if missing_fail_to_pass:
            print(f"Error: The following FAIL_TO_PASS tests did not pass after the patch: {missing_fail_to_pass}")
            return False

        missing_pass_to_pass = pass_to_pass - tests_passed_after
        if missing_pass_to_pass:
            print(f"Error: The following PASS_TO_PASS tests did not pass after the patch: {missing_pass_to_pass}")
            return False

        print(f"Successfully validated data point: {data_point_path}")
        return True


def main():
    parser = argparse.ArgumentParser(description="Validate SWE-bench data points.")
    parser.add_argument(
        "data_points_path",
        type=str,
        help="Path to a single data point JSON file or a directory containing data point files.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=1800,
        help="Timeout in seconds for each evaluation.",
    )
    args = parser.parse_args()

    data_points_path = Path(args.data_points_path)
    if data_points_path.is_file():
        files_to_validate = [data_points_path]
    elif data_points_path.is_dir():
        files_to_validate = list(data_points_path.glob("*.json"))
    else:
        print(f"Error: Invalid path: {data_points_path}")
        sys.exit(1)

    if not files_to_validate:
        print(f"No JSON files found in {data_points_path}")
        sys.exit(1)

    all_successful = True
    for file_path in files_to_validate:
        if not validate_data_point(file_path, args.timeout):
            all_successful = False

    if all_successful:
        print("All data points validated successfully.")
    else:
        print("Some data points failed validation.")
        sys.exit(1)


if __name__ == "__main__":
    main()