# 🔒 Security Policy

## Supported Versions

We release patches for security vulnerabilities in the following versions:

| Version | Supported          |
| ------- | ------------------ |
| 0.1.x   | ✅ Yes             |

## 🛡️ Security Model

### How erdify Works

This tool uses Python's `ast` module to parse model files as text. It:

- ✅ **Does NOT execute** any Python code from the parsed files
- ✅ **Does NOT import** any modules from the parsed files
- ✅ **Does NOT connect** to any database
- ✅ **Does NOT send** any data over the network
- ✅ Has **zero runtime dependencies** (stdlib only)

### What This Means

- The tool is safe to run on untrusted model files
- Malicious code in model files cannot be executed
- No risk of SQL injection or database access
- No network-based attacks possible

## 🚨 Reporting a Vulnerability

We take security seriously. If you discover a security vulnerability, please report it responsibly.

### How to Report

1. **DO NOT** open a public GitHub issue for security vulnerabilities
2. Email us at: [security@devsuit.de](mailto://security@devsuit.de)
3. Include:
   - Description of the vulnerability
   - Steps to reproduce
   - Potential impact
   - Any suggested fixes (optional)

### What to Expect

- **Acknowledgment**: Within 48 hours
- **Initial Assessment**: Within 1 week
- **Resolution Timeline**: Depends on severity
  - 🔴 Critical: 24-48 hours
  - 🟠 High: 1 week
  - 🟡 Medium: 2 weeks
  - 🟢 Low: Next release

### After Reporting

1. We'll investigate and validate the issue
2. We'll work on a fix
3. We'll coordinate disclosure timing with you
4. We'll credit you in the release notes (unless you prefer anonymity)

## 🔐 Best Practices for Users

While erdify is designed to be safe, we recommend:

1. **Keep Updated**: Use the latest version
2. **Review Output**: Check generated diagrams before sharing
3. **CI/CD Security**: Run in isolated environments
4. **Input Validation**: Only process trusted directories

## 📋 Security Checklist for Contributors

When contributing, ensure:

- [ ] No use of `eval()`, `exec()`, or `__import__()`
- [ ] No dynamic code execution
- [ ] No file operations outside specified paths
- [ ] No network requests
- [ ] Input validation for all user-provided paths
- [ ] Tests for edge cases and malformed input

## 🏆 Security Hall of Fame

We thank the following individuals for responsibly disclosing security issues:

*No reports yet - be the first!*

---

Thank you for helping keep erdify secure! 🙏
