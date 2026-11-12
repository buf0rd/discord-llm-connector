# Contributing

Changes to the Python application belong in `src/`. `install.sh` copies these sources into a temporary staging directory, runs the unit tests, backs up existing managed files, and installs under `/opt/discord-llm`.

To run the local tests after installing dependencies:

```bash
bash install.sh --test-only
```

Please avoid posting tokens, credentials, private Discord messages, full bot logs containing sensitive context, or real-world home addresses/IP addresses in issues and pull requests. Submit bug reports with sanitized configuration and reproduction steps.

This project is licensed under the [MIT License](LICENSE). By contributing, you agree that your contribution will be distributed under that license, unless explicitly agreed otherwise.
