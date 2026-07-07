# Real CSV Fixture Drop Zone

Put real multi-header measurement CSV exports here, including WinWert-like
files. `tests/test_csv_header_loading.py::test_real_samples_load` collects
`*.csv` files in this directory as regression samples. If the directory has no
CSV files, pytest collects zero parametrized cases for that test.
