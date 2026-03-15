# ☁️ AWS Cloud Cost Autopilot

> A fully serverless AWS automation system that hunts down cloud waste every night, automatically remediates it, and emails you a weekly cost savings report — with zero manual intervention.

---

## 📌 Project Overview

**AWS Cloud Cost Autopilot** is a DevOps automation project built entirely on AWS serverless services. It solves one of the most common and costly problems in cloud engineering — **unnoticed resource waste**.

Cloud bills can silently grow due to:
- EC2 instances running 24/7 with no actual workload
- EBS snapshots accumulating for months, never cleaned up
- No visibility into which services are driving costs week to week

This project **fully automates** the detection, remediation, and reporting of all three problems using AWS Lambda, EventBridge, SNS, CloudWatch, and Cost Explorer — running on the **AWS Free Tier** at a cost of less than **$0.08/month**.

---

## 🏗️ Architecture

```
EventBridge Scheduler (cron: 0 2 * * ? *)
         |
         |── triggers ──► Lambda #1: idle-ec2-stopper
         |                    └─ Scans all running EC2 instances
         |                    └─ Checks 24h average CPU via CloudWatch
         |                    └─ Stops instances with CPU < 5%
         |                    └─ Tags stopped instances with reason + timestamp
         |
         |── triggers ──► Lambda #2: snapshot-cleaner
         |                    └─ Scans all EBS snapshots (self-owned)
         |                    └─ Builds protected set from active AMIs
         |                    └─ Deletes orphaned snapshots older than 30 days
         |                    └─ Logs total storage freed (GB)
         |
         └── triggers ──► Lambda #3: cost-reporter
                              └─ Queries AWS Cost Explorer (last 7 days)
                              └─ Builds cost breakdown by service
                              └─ Publishes report to SNS Topic
                                         └─ Delivers email to subscribed address
```

---

## 🛠️ Tech Stack

| Service | Purpose |
|---|---|
| **AWS Lambda** | Serverless compute — runs all automation logic |
| **Amazon EventBridge** | Cron-based scheduler — triggers Lambdas nightly at 2AM UTC |
| **AWS IAM** | Least-privilege Role and Policy for Lambda permissions |
| **Amazon CloudWatch** | EC2 CPU metrics source + Lambda execution logs |
| **AWS Cost Explorer** | Billing data API — weekly cost breakdown by service |
| **Amazon SNS** | Email delivery for weekly cost reports |
| **Python 3.11** | Runtime language for all Lambda functions |
| **boto3** | AWS SDK for Python — used in all Lambda functions |

---

## 📁 Project Structure

```
aws-cost-autopilot/
│
├── iam/
│   ├── cost-optimizer-policy.json      # IAM permissions policy
│   └── lambda-trust-policy.json        # Lambda trust relationship
│
├── lambdas/
│   ├── idle_ec2_stopper/
│   │   └── lambda_function.py          # Lambda #1 — stops idle EC2s
│   │
│   ├── snapshot_cleaner/
│   │   └── lambda_function.py          # Lambda #2 — cleans old snapshots
│   │
│   └── cost_reporter/
│       └── lambda_function.py          # Lambda #3 — emails cost report
│
├── eventbridge/
│   └── scheduler.json                  # EventBridge rule configuration
│
├── sns/
│   └── topic-config.json               # SNS topic configuration
│
└── README.md
```

---

## ⚙️ Implementation Details

### Phase 1 — IAM Setup (Security Foundation)

Before any Lambda function can interact with AWS services, it needs a secure identity. We implemented this following the **Principle of Least Privilege**:

**CostOptimizerPolicy** — a custom IAM policy granting only:
- `ec2:DescribeInstances`, `ec2:StopInstances` — to scan and stop idle servers
- `ec2:DescribeSnapshots`, `ec2:DeleteSnapshot`, `ec2:DescribeImages` — to manage EBS snapshots
- `cloudwatch:GetMetricStatistics` — to read CPU metrics
- `logs:CreateLogGroup`, `logs:CreateLogStream`, `logs:PutLogEvents` — for Lambda logging
- `ce:GetCostAndUsage` — to pull billing data
- `sns:Publish` — to send email reports

**CostOptimizerRole** — an IAM Role with a trust policy that allows `lambda.amazonaws.com` to assume it. All three Lambda functions share this single role.

---

### Phase 2 — Lambda #1: Idle EC2 Stopper

**File:** `lambdas/idle_ec2_stopper/lambda_function.py`

**How it works:**
1. Uses `boto3` EC2 client to fetch all instances in `running` state
2. For each instance, queries CloudWatch `GetMetricStatistics` API for the 24-hour average `CPUUtilization`
3. If average CPU is below **5%** (or no data exists), the instance is stopped via `stop_instances()`
4. Tags each stopped instance with three metadata keys:
   - `AutoStopped: true`
   - `AutoStoppedAt: <timestamp>`
   - `Reason: CPU below 5% for 24 hours`
5. Returns a summary of stopped vs skipped instances

**Why tagging matters:** Tags make it immediately visible in the EC2 console why an instance was stopped — preventing confusion and enabling easy auditing.

---

### Phase 3 — Lambda #2: Snapshot Cleaner

**File:** `lambdas/snapshot_cleaner/lambda_function.py`

**How it works:**
1. Fetches all EBS snapshots owned by the account using `describe_snapshots(OwnerIds=['self'])`
2. Builds a **protected set** — fetches all AMIs owned by the account and extracts every snapshot ID referenced in their block device mappings. These are NEVER deleted.
3. Defines a cutoff date of **30 days ago**
4. For each snapshot, applies two safety gates:
   - **Gate 1:** Is it in the protected set? → Skip
   - **Gate 2:** Is it newer than 30 days? → Skip
5. Only snapshots that pass both gates are deleted via `delete_snapshot()`
6. Tracks and returns total storage freed in GB

**Safety-first design:** It is architecturally impossible for this function to delete a snapshot that is actively backing an AMI or that was created within the last 30 days.

---

### Phase 4 — SNS Email Setup

Created an **SNS Standard Topic** (`CostReportTopic`) and subscribed an email address to it using the `email` protocol. SNS acts as the delivery layer between the Lambda function and the end user — decoupling the report generation logic from the notification mechanism.

The email subscription was confirmed via the AWS confirmation link sent to the inbox.

The **SNS Topic ARN** is stored as a Lambda **environment variable** (`SNS_TOPIC_ARN`) — following best practice of never hardcoding resource identifiers in source code.

---

### Phase 5 — Lambda #3: Cost Reporter

**File:** `lambdas/cost_reporter/lambda_function.py`

**How it works:**
1. Reads `SNS_TOPIC_ARN` from environment variables
2. Queries **AWS Cost Explorer** `get_cost_and_usage` API for the past 7 days to get total spend
3. Makes a second Cost Explorer call with `GroupBy SERVICE` dimension to get per-service cost breakdown
4. Filters out services with less than $0.01 spend (noise reduction)
5. Sorts services by cost — highest first
6. Builds a formatted plain-text email report with:
   - Date range
   - Total cost in USD
   - Service-by-service breakdown with visual bar chart using ASCII characters
7. Publishes the report to the SNS topic via `sns.publish()`
8. SNS delivers the email to all confirmed subscribers

---

### Phase 6 — EventBridge Scheduler (The Automation Engine)

Created an **EventBridge Rule** (`DailyCostOptimizer`) with a cron expression:

```
cron(0 2 * * ? *)
```

This means: **every day at 02:00 AM UTC** — all three Lambda functions fire automatically.

All three Lambdas were attached as **targets** of this single rule. EventBridge was granted `lambda:InvokeFunction` permission on each function automatically during rule creation.

**Result:** From this point forward, the entire system runs on autopilot — no human input required.

---

## 💰 Real-World Cost & Savings

### What this project saves:

| Resource | Monthly Savings |
|---|---|
| Idle EC2 instances auto-stopped | $40 – $120 |
| Orphaned EBS snapshots deleted | $10 – $30 |
| Cost visibility (prevents surprises) | Priceless |
| **Total estimated savings** | **$50 – $160/month** |

### What this project costs to run:

| Service | Monthly Cost |
|---|---|
| AWS Lambda | $0.00 (Free Tier) |
| Amazon EventBridge | $0.00 (Free Tier) |
| Amazon SNS | $0.00 (Free Tier) |
| Amazon CloudWatch | $0.00 (Free Tier) |
| AWS Cost Explorer API | ~$0.08 (8 API calls/month × $0.01) |
| **Total** | **~$0.08/month** |

---

## 🚀 How to Deploy

### Prerequisites
- AWS Account (Free Tier)
- AWS CLI installed and configured
- Python 3.11

### Step 1 — Create IAM Policy & Role
```bash
aws iam create-policy \
  --policy-name CostOptimizerPolicy \
  --policy-document file://iam/cost-optimizer-policy.json

aws iam create-role \
  --role-name CostOptimizerRole \
  --assume-role-policy-document file://iam/lambda-trust-policy.json

aws iam attach-role-policy \
  --role-name CostOptimizerRole \
  --policy-arn arn:aws:iam::YOUR_ACCOUNT_ID:policy/CostOptimizerPolicy
```

### Step 2 — Deploy Lambda Functions
```bash
# Lambda #1
cd lambdas/idle_ec2_stopper
zip deployment.zip lambda_function.py
aws lambda create-function \
  --function-name idle-ec2-stopper \
  --runtime python3.11 \
  --role arn:aws:iam::YOUR_ACCOUNT_ID:role/CostOptimizerRole \
  --handler lambda_function.lambda_handler \
  --zip-file fileb://deployment.zip \
  --timeout 60 --region us-east-1

# Lambda #2
cd ../snapshot_cleaner
zip deployment.zip lambda_function.py
aws lambda create-function \
  --function-name snapshot-cleaner \
  --runtime python3.11 \
  --role arn:aws:iam::YOUR_ACCOUNT_ID:role/CostOptimizerRole \
  --handler lambda_function.lambda_handler \
  --zip-file fileb://deployment.zip \
  --timeout 60 --region us-east-1

# Lambda #3
cd ../cost_reporter
zip deployment.zip lambda_function.py
aws lambda create-function \
  --function-name cost-reporter \
  --runtime python3.11 \
  --role arn:aws:iam::YOUR_ACCOUNT_ID:role/CostOptimizerRole \
  --handler lambda_function.lambda_handler \
  --zip-file fileb://deployment.zip \
  --timeout 60 --region us-east-1
```

### Step 3 — Create SNS Topic & Subscribe Email
```bash
aws sns create-topic --name CostReportTopic --region us-east-1

aws sns subscribe \
  --topic-arn arn:aws:sns:us-east-1:YOUR_ACCOUNT_ID:CostReportTopic \
  --protocol email \
  --notification-endpoint your@email.com \
  --region us-east-1
# Check inbox and confirm the subscription email
```

### Step 4 — Set Up EventBridge Scheduler
```bash
aws events put-rule \
  --name DailyCostOptimizer \
  --schedule-expression "cron(0 2 * * ? *)" \
  --state ENABLED --region us-east-1

aws events put-targets \
  --rule DailyCostOptimizer --region us-east-1 \
  --targets \
    "Id=IdleEC2Stopper,Arn=arn:aws:lambda:us-east-1:YOUR_ACCOUNT_ID:function:idle-ec2-stopper" \
    "Id=SnapshotCleaner,Arn=arn:aws:lambda:us-east-1:YOUR_ACCOUNT_ID:function:snapshot-cleaner" \
    "Id=CostReporter,Arn=arn:aws:lambda:us-east-1:YOUR_ACCOUNT_ID:function:cost-reporter"
```

---

## 📊 What the Weekly Email Looks Like

```
AWS Weekly Cost Report
========================================
Period : 2026-03-08 to 2026-03-15
Total  : $4.32 USD
========================================

Cost by Service:

  $ 2.10  xxxxxxxxxxxx  Amazon EC2
  $ 1.20  xxxxxxx       Amazon RDS
  $ 0.80  xxxx          Amazon S3
  $ 0.22  x             AWS Lambda

========================================
Sent by AWS Cost Autopilot
Generated: 2026-03-15 02:00 UTC
```

---

## 🔐 Security Highlights

- **Principle of Least Privilege** — Lambda only has the exact permissions it needs, nothing more
- **No hardcoded credentials** — all resource ARNs stored as environment variables
- **Safe deletion logic** — snapshot cleaner has two independent safety gates before any deletion
- **Audit trail** — all stopped instances are tagged with reason and timestamp

---

## 📈 Skills Demonstrated

- AWS Lambda function development with Python (boto3)
- IAM Role and Policy creation with least-privilege design
- CloudWatch metrics querying for resource monitoring
- EventBridge cron scheduling and multi-target rules
- SNS topic creation and email subscription management
- AWS Cost Explorer API integration
- Serverless event-driven architecture design
- AWS Console and AWS CLI proficiency

---

## 📌 Topics

`aws` `lambda` `serverless` `python` `boto3` `devops` `cloud-cost-optimization` `eventbridge` `sns` `cloudwatch` `iam` `automation` `aws-lambda` `cost-optimization` `ebs` `ec2`

---

> Built as a beginner DevOps project to learn AWS serverless architecture through real-world cost optimization automation.
