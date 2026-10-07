# macOS host dependencies; Python packages and lint tools are installed from poetry.lock.
# Install Poetry 2.5.1 with pipx as documented in README.md to match the CI bootstrap.
brew "python@3.13"
brew "pipx"

# Repository scripts, GitHub publication, and signing-key fingerprints.
brew "bash"
brew "git"
brew "gh"
brew "jq"
brew "cosign"
brew "openssl@3"

# Validate GitHub Actions locally; ShellCheck and shfmt come from Poetry's dev group.
brew "actionlint"

# The browser client expects Firefox in /Applications; Selenium manages geckodriver.
cask "firefox", args: { appdir: "/Applications" }

# Local PDF compilation uses the pinned TeX image, so no host TeX installation is needed.
cask "docker-desktop"
