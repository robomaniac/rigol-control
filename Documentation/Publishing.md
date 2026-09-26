# Publish to GitHub

The repository is [robomaniac/rigol-control](https://github.com/robomaniac/rigol-control).
Run the commands below from the project root when preparing later changes.
Git commit identity and GitHub login are separate settings.

## Commit name and email

```bash
git config --global user.name "Your display name"
git config --global user.email "YOUR_EMAIL"
```

Omitting the last argument reads the current value. GitHub associates commits
with your account using the email; use a verified email or your account's exact
noreply address from GitHub Settings → Emails. Your Git name can be a display
name rather than your GitHub username. See GitHub's documentation for
[commit email](https://docs.github.com/en/account-and-profile/how-tos/email-preferences/setting-your-commit-email-address)
and [Git username](https://docs.github.com/en/get-started/git-basics/setting-your-username-in-git).

## Check the files

```bash
python -m pytest
git status --short
git check-ignore Software/config/lab.yaml
```

The local inventory, `Data/Runs/`, `Data/Logs/`, environment and caches
must stay out of commits. The reviewed reports/CSV and redacted example under
`Data/Example_Run/` are intended to be shared. `.gitignore` cannot remove
something from old commits.
Choose an appropriate license before publishing for reuse.

## Push later changes

A clone already has an `origin` remote. Review the staged files before committing
and pushing your updates:

```bash
git add README.md pyproject.toml .gitignore .vscode .nojekyll index.html Documentation Electrical Media Data Software
git diff --cached --stat
git diff --cached --name-only
git commit -m "Update bench control documentation and reports"
git push origin main
```

For a fork, push to your fork's remote. An SSH remote requires a GitHub SSH key
on the machine pushing the changes; an HTTPS remote uses GitHub's supported
authentication methods. Do not place tokens or private keys in this project.
Setting `user.name` and `user.email` does not log in or upload anything.

## Publish the HTML reports with GitHub Pages

GitHub's repository file view displays HTML source code. GitHub Pages serves
the reports as interactive web pages, so visitors do not need the Pi or an SSH
connection. The reports are self-contained files and also work when downloaded
and opened locally.

After the files are on `main`, open the repository on GitHub:

1. Go to **Settings → Pages**.
2. Under **Build and deployment → Source**, choose **Deploy from a branch**.
3. Select **main** and **/(root)**, then click **Save**.
4. Wait for the Pages deployment to finish; the Pages settings show the site URL.

Later pushes to `main` publish updated files automatically. See
[GitHub's publishing-source instructions](https://docs.github.com/en/pages/getting-started-with-github-pages/configuring-a-publishing-source-for-your-github-pages-site).

The root `index.html` opens the real power test, and `.nojekyll` lets Pages serve
the saved static files directly. Report links are:

- [Real 21-point power test](https://robomaniac.github.io/rigol-control/Data/power-test-report.html)
- [Simulated example](https://robomaniac.github.io/rigol-control/Data/sweep-preview.html)
- [Original three-point test](https://robomaniac.github.io/rigol-control/Data/demo-report.html)

For a fork, enable Pages in that repository and replace
`https://robomaniac.github.io/rigol-control/` in the README and documentation with
`https://YOUR_USERNAME.github.io/YOUR_REPOSITORY/`. Keep the `Data/` path and report
filenames after that prefix. The relative link in `index.html` works under the
fork's repository URL too.
