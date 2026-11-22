import os

os.environ.setdefault("GRPC_VERBOSITY", "ERROR")
os.environ.pop("PITBOARD_SCHEMA", None)
