# BalanceZero

A YNAB-style zero-based budgeting web app, connected to real bank data via [SimpleFIN Bridge](https://www.simplefin.org/). Every dollar of income gets assigned to a category each month (income − allocated = 0), and unspent/overspent category balances roll forward month to month.

Built as a portfolio/cornerstone project applying a full DevOps pipeline (Docker, CI/CD, Kubernetes, AWS) and dedicated web security practices to one real application, rather than practice repos.

## Status

Early scaffolding. Nothing functional yet.

## Design

Two users from day one: a real account (real SimpleFIN connection, real bank data) and a seeded demo account (synthetic data, no real bank connection) — so the app can be shown publicly without ever exposing real financial data.

Full scope, data model plan, SimpleFIN integration details, and security requirements: see the planning doc from this project's originating course repo.

## Stack

- Flask, server-rendered templates
- Postgres in production (SQLite for local dev)
- Docker, GitHub Actions CI/CD
- Deploy target: not yet decided (ECS/Fargate vs EKS)

## Local setup

```
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python3 app.py
```

Runs on port 5002 (5000 conflicts with macOS's AirPlay Receiver, 5001 is used by the `security-practice` exercise from lesson 0012).
