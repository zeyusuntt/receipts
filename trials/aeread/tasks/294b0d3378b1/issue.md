The open-harness capture client picks the wrong HTTP transport for the OpenAI SDK.

`_capture_http_client` in `aeread/shared_runner/open_harnesses.py` uses `httpx` for every OpenAI SDK from major version 2 up, and tries `httpx2` only for older majors. OpenAI SDK 3.x is built on `httpx2`, so with SDK 3 installed the capture client is built on the wrong library. The transport should follow the SDK major: `httpx2.Client` for OpenAI SDK 3.x, `httpx.Client` for 2.x.
