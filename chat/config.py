"""Which backend answers the chat.

``"local"`` -- the built-in assistant engine (``assistant/answers.py``): runs on
this computer, reads the local database, needs no download.  ``"cloud"`` is a
placeholder for a future remote backend (see ``backend_cloud.py``).
"""

BACKEND = "local"
CLOUD_URL = ""

import os

#: Let the local language model (``llm/``) answer general questions the engine cannot
#: ("how do I build a CNN?").  Set the environment variable OFFICE_LLM=0 to switch it
#: off (the engine then answers everything, as before).
LLM_ENABLED = os.environ.get("OFFICE_LLM", "1") != "0"

#: How many earlier question/answer pairs of the chat the model gets as memory.
LLM_HISTORY_PAIRS = 6
