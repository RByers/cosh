# Tests never touch the network: OrgResolver() would otherwise refresh
# config/affiliations.json5 from chromium/src (cosh/orgs.py).
import os

os.environ["COSH_AFFILIATIONS_OFFLINE"] = "1"
