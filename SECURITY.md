# Security Policy

## Supported Versions

We release security fixes for the latest published version only. Always run the
most recent release.

| Version        | Supported |
| -------------- | --------- |
| Latest release | Yes       |
| Older          | No        |

## Security Model

### The core install

`pip install erdify` has **no runtime dependencies** and parses model files with
Python's standard-library `ast` module. For that install, erdify:

- does **not execute** any code from the files it reads
- does **not import** any module from the files it reads
- does **not open** a database connection
- does **not make** network requests

So a malicious `models.py` cannot get its code run by pointing erdify at it, and
the only third-party code in the process is erdify itself.

### The `sql` extra

`pip install erdify[sql]` adds one dependency,
[sqlglot](https://github.com/tobymao/sqlglot), which parses `.sql` files. The
statements above about not executing, importing or connecting still hold — but
the trust boundary is wider: sqlglot is third-party code running in your
process, and a vulnerability in it is a vulnerability in your `erdify[sql]`
install. Weigh that the way you would any other dependency, and keep it updated.

### Filesystem writes

erdify writes where you tell it to: `--output` creates or overwrites the target
file, and `--inject` rewrites the region between the markers in the Markdown
file you name. It does not write anywhere else, and it never deletes. Treat
those paths as you would any other output path in a pipeline — in particular,
do not build them from untrusted input.

### What is not covered

- The **rendering** step. erdify emits PlantUML, Mermaid, JSON or HTML; what
  you then feed a PlantUML server, a Mermaid renderer or a browser is outside
  erdify's control. Entity, column and enum names from the parsed source appear
  verbatim in that output.
- Anything erdify is pointed at that it does not parse.

## Reporting a Vulnerability

Please report vulnerabilities privately.

1. **Do not** open a public GitHub issue for a security vulnerability.
2. Email [tech@devsuit.de](mailto:tech@devsuit.de).
3. Include a description, steps to reproduce, the potential impact, and any
   suggested fix.

### What to expect

erdify is maintained by a small team, so the times below are what we aim for
rather than a guaranteed service level:

- **Acknowledgment**: usually within a few business days.
- **Initial assessment**: once we have reproduced it, we will tell you whether
  we consider it a vulnerability and roughly how we plan to handle it.
- **Fix**: as fast as the severity warrants. A critical issue takes priority
  over everything else; a low-severity one ships with the next release.

If you have not heard back within a week, please send a reminder — mail does go
astray.

### After reporting

1. We investigate and validate the issue.
2. We work on a fix.
3. We coordinate disclosure timing with you.
4. We credit you in the release notes, unless you prefer to stay anonymous.

## Recommendations for Users

- Run the latest release.
- Run erdify in an isolated environment in CI, as you would any build step.
- Review generated diagrams before publishing them: they contain your table,
  column and enum names, which can themselves be sensitive.

## Security Checklist for Contributors

When contributing, make sure there is:

- [ ] no `eval()`, `exec()` or `__import__()`
- [ ] no dynamic code execution
- [ ] no file operations outside the paths the user specified
- [ ] no network requests
- [ ] validation of user-provided paths
- [ ] test coverage for edge cases and malformed input

## Acknowledgments

Our thanks to everyone who has reported a security issue responsibly:

*No reports yet.*
