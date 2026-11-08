@echo off
REM GCP project migration offofby -> offorby (run by the user once)
REM Creates project, links billing, enables APIs, monthly budget, 2 service accounts + keys, switches local default project.
REM BigQuery table copy and views are NOT here (Claude runs them with approval).
REM ASCII only: cmd.exe on Korean Windows reads this file as CP949, so no Korean text here.
setlocal
set PROJECT=offorby
set BILLING=01AE19-D00EA0-045997

echo [1/7] create project
call gcloud.cmd projects describe %PROJECT% --format=none >nul 2>&1
if errorlevel 1 (
  call gcloud.cmd projects create %PROJECT% --name=Offorby --format=none
  if errorlevel 1 (
    echo Cannot create project ID %PROJECT%. If the ID is already taken globally, change PROJECT in this script, e.g. offorby-kr, and rerun.
    exit /b 1
  )
) else (
  echo project %PROJECT% already exists, skipping create
  call gcloud.cmd projects update %PROJECT% --name=Offorby --format=none
)

echo [2/7] link billing
call gcloud.cmd billing projects link %PROJECT% --billing-account=%BILLING% --format=none

echo [3/7] enable APIs
call gcloud.cmd services enable bigquery.googleapis.com billingbudgets.googleapis.com --project=%PROJECT%

echo [4/7] monthly budget 290,000 KRW (alerts at 50/90/100%%)
call gcloud.cmd billing budgets create --billing-account=%BILLING% --display-name=offorby-monthly --budget-amount=290000KRW --filter-projects=projects/%PROJECT% --threshold-rule=percent=0.5 --threshold-rule=percent=0.9 --threshold-rule=percent=1.0 --format=none

echo [5/7] service accounts
call gcloud.cmd iam service-accounts create offorby-web --project=%PROJECT% --display-name="Offorby web (read-only)" --format=none
call gcloud.cmd iam service-accounts create offorby-writer --project=%PROJECT% --display-name="Offorby pipeline writer" --format=none

echo [6/7] IAM roles
call gcloud.cmd projects add-iam-policy-binding %PROJECT% --member=serviceAccount:offorby-web@%PROJECT%.iam.gserviceaccount.com --role=roles/bigquery.dataViewer --condition=None --format=none
call gcloud.cmd projects add-iam-policy-binding %PROJECT% --member=serviceAccount:offorby-web@%PROJECT%.iam.gserviceaccount.com --role=roles/bigquery.jobUser --condition=None --format=none
call gcloud.cmd projects add-iam-policy-binding %PROJECT% --member=serviceAccount:offorby-writer@%PROJECT%.iam.gserviceaccount.com --role=roles/bigquery.dataEditor --condition=None --format=none
call gcloud.cmd projects add-iam-policy-binding %PROJECT% --member=serviceAccount:offorby-writer@%PROJECT%.iam.gserviceaccount.com --role=roles/bigquery.jobUser --condition=None --format=none

echo [7/7] keys (secrets\ is gitignored)
if not exist secrets mkdir secrets
call gcloud.cmd iam service-accounts keys create secrets\offorby-web-sa.json --iam-account=offorby-web@%PROJECT%.iam.gserviceaccount.com
call gcloud.cmd iam service-accounts keys create secrets\offorby-writer-sa.json --iam-account=offorby-writer@%PROJECT%.iam.gserviceaccount.com

call gcloud.cmd config set project %PROJECT%
call gcloud.cmd auth application-default set-quota-project %PROJECT%

echo.
echo DONE. Next:
echo  - GitHub Secrets: replace GCP_SA_KEY_WRITER with contents of secrets\offorby-writer-sa.json
echo  - Vercel env: GCP_PROJECT=offorby, BQ_DATASET=offorby, GCP_SA_KEY = contents of secrets\offorby-web-sa.json
echo  - Tell Claude "BigQuery copy" to copy tables and create views (with approval)
endlocal
