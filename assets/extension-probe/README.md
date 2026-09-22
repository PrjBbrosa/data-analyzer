# Fixed native probe fixtures

Generated locally with `tools.verify_lite_importer_runtime.create_fixtures`.
These tiny synthetic WAV, MP4/AAC, traditional MAT and HDF5 MAT files contain
no user data. Ship them in the target analyzer, not the independent manager.
The manager invokes the target child; the child verifies selected module origins
and reads these exact files through the production importers.
