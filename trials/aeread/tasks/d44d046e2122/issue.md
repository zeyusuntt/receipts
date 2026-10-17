`aeread.integrations.rllm_dataset` resolves its default case glob against the process's current working directory. `python -m aeread.integrations.rllm_dataset --register` therefore only works when it is run from inside a checkout of the repository; run from any other directory, `build_rows()` finds no case configs and raises `FileNotFoundError`.

The default case set should be found wherever the process is started. A glob the caller passes explicitly should keep working as it does now.
