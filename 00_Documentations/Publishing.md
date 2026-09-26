# Publish to GitHub

Run these commands from the project root. Git commit identity and GitHub
login are separate settings.

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
git check-ignore 08_Software/config/lab.yaml
```

The local inventory, `05_Data/Runs/`, `05_Data/Logs/`, environment and caches
must stay out of commits. The reviewed reports/CSV and redacted example under
`05_Data/Example_Run/` are intended to be shared. `.gitignore` cannot remove
something from old commits.
Choose an appropriate license before publishing for reuse.

## First commit and push

If this folder has not been initialized, run `git init -b main` first.
Create an empty GitHub repository (without generated README or license),
then replace `YOUR_REPOSITORY` in the remote URL below:

```bash
git add README.md pyproject.toml .gitignore .vscode 00_Documentations 01_Electrical 04_Media 05_Data 08_Software
git diff --cached --stat
git diff --cached --name-only
git commit -m "Add Rigol bench control and measured demo"
git remote add origin git@github.com:robomaniac/YOUR_REPOSITORY.git
git push -u origin main
```

The SSH URL requires a GitHub SSH key on the Pi. Alternatively use an HTTPS
remote and GitHub's supported authentication method. Do not place tokens or
private keys in this project. Setting `user.name` and `user.email` does not log
in or upload anything.
