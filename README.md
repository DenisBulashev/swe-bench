# SWE-bench Validator

This project contains the validation tools for the SWE-bench dataset. It provides a way to ensure that new data points added to the dataset are well-formed and that the provided patches work as expected.

## How to use

The main tool is the `validate_data_points.py` script. You can use it to validate a single data point file or a directory of them.

### Prerequisites

*   Python 3.8+
*   Docker

### Installation

1.  Clone this repository.
2.  Install the dependencies:
    ```bash
    pip install -e .
    ```

### Running the validator

To validate all data points in the `data_points` directory, run:
```bash
python -m validation.validate_data_points data_points/
```

To validate a single data point:
```bash
python -m validation.validate_data_points data_points/astropy__astropy-11693.json
```

You can also specify a timeout for the validation:
```bash
python -m validation.validate_data_points data_points/ --timeout 600
```

## GitHub Action

This repository also includes a GitHub Action that automatically validates new or modified data points in pull requests. The workflow is defined in `.github/workflows/validate-datapoints.yml`.