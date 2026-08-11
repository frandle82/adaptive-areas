# Contribution guidelines

Contributing to this project should be as easy and transparent as possible, whether it's:

- Reporting a bug
- Discussing the current state of the code
- Submitting a fix
- Proposing new features
- Helping with translation

## GitHub is used for (almost) everything

GitHub is used to host code, track issues and feature requests, and accept pull requests. Translation updates are accepted as pull requests as well.

Pull requests are the best way to propose changes to the codebase.

1. Fork the repo and create your branch from `main`.
2. If you've changed (or added) something, update the documentation.
3. Make sure your code lints (using `scripts/lint`).
4. Test your contribution (using `scripts/test`). Contributions that don't provide tests may take longer to be incorporated.
5. Issue that pull request!

## Commit messages

This repository uses [Conventional Commits](https://www.conventionalcommits.org/). Stage the files that belong to the commit and use the helper to validate the message and run all configured hooks:

```bash
git add <files>
scripts/commit "feat(area): add occupancy strategy"
```

Supported types are `build`, `chore`, `ci`, `docs`, `feat`, `fix`, `perf`, `refactor`, `revert`, `style`, and `test`. Pull-request titles and all commits are validated in CI.

## Releases

Every push to `main` updates a release draft from merged pull requests. To create a draft, pre-release, or final release, run the **Create Release** workflow from GitHub Actions and enter a semantic version without a leading `v`.

- Draft: `1.2.3` or `1.2.3-rc.1`
- Pre-release: a suffixed version such as `1.2.3-beta.1` or `1.2.3-rc.1`
- Release: a stable version such as `1.2.3`

The workflow validates the version, updates the integration manifest, creates a `chore(release)` commit, and creates or publishes the matching GitHub release.

## Any contributions you make will be under the MIT Software License

In short, when you submit code changes, your submissions are understood to be under the same [MIT License](http://choosealicense.com/licenses/mit/) that covers the project. Feel free to contact the maintainers if that's a concern.

## Report bugs using GitHub's [issues](https://github.com/frandle82/adaptive-areas/issues)

GitHub issues are used to track public bugs.
Report a bug by [opening a new issue](https://github.com/frandle82/adaptive-areas/issues/new/choose); it's that easy!

## Write bug reports with detail, background, and sample code

**Great Bug Reports** tend to have:

- A quick summary and/or background
- Steps to reproduce
  - Be specific!
  - Give sample code if you can.
- What you expected would happen
- What actually happens
- Notes (possibly including why you think this might be happening, or stuff you tried that didn't work)

People *love* thorough bug reports. I'm not even kidding.

## Use a Consistent Coding Style

Use [black](https://github.com/ambv/black) to make sure the code follows the style. (Running `scripts/lint` will run `black`)

## Test your code modification

This custom component is based on [integration_blueprint template](https://github.com/ludeeus/integration_blueprint).

It comes with development environment in a container, easy to launch if you use Visual Studio Code. With this container you will have a stand alone Home Assistant instance running and already configured with the included [`configuration.yaml`](./config/configuration.yaml) file.

If you need help with your environment or understanding the code, open a topic in [GitHub Discussions](https://github.com/frandle82/adaptive-areas/discussions).

## License

By contributing, you agree that your contributions will be licensed under its MIT License.
