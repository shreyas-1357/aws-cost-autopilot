import boto3
from datetime import datetime, timedelta, timezone

def lambda_handler(event, context):
    ec2 = boto3.client('ec2', region_name='us-east-1')
    cw  = boto3.client('cloudwatch', region_name='us-east-1')

    print("🔍 Scanning for idle EC2 instances...")

    # Step 1: Get all RUNNING instances
    response = ec2.describe_instances(
        Filters=[{'Name': 'instance-state-name', 'Values': ['running']}]
    )

    stopped = []
    skipped = []

    for reservation in response['Reservations']:
        for instance in reservation['Instances']:
            instance_id = instance['InstanceId']

            # Step 2: Get average CPU for last 24 hours
            cpu_stats = cw.get_metric_statistics(
                Namespace='AWS/EC2',
                MetricName='CPUUtilization',
                Dimensions=[{'Name': 'InstanceId', 'Value': instance_id}],
                StartTime=datetime.now(timezone.utc) - timedelta(hours=24),
                EndTime=datetime.now(timezone.utc),
                Period=86400,
                Statistics=['Average']
            )

            datapoints = cpu_stats['Datapoints']

            # Step 3: If no data OR avg CPU < 5%, stop it
            if not datapoints or datapoints[0]['Average'] < 5.0:
                print(f"  ⚠️  {instance_id} is idle — stopping...")

                # Stop the instance
                ec2.stop_instances(InstanceIds=[instance_id])

                # Tag it so we know WHY it was stopped
                ec2.create_tags(
                    Resources=[instance_id],
                    Tags=[
                        {'Key': 'AutoStopped', 'Value': 'true'},
                        {'Key': 'AutoStoppedAt', 'Value': str(datetime.now(timezone.utc))},
                        {'Key': 'Reason', 'Value': 'CPU below 5% for 24 hours'}
                    ]
                )
                stopped.append(instance_id)

            else:
                avg_cpu = round(datapoints[0]['Average'], 2)
                print(f"  ✅  {instance_id} is active (CPU: {avg_cpu}%) — skipping")
                skipped.append(instance_id)

    # Step 4: Summary
    print(f"\n📊 Done. Stopped: {len(stopped)} | Skipped: {len(skipped)}")
    print(f"Stopped instances: {stopped}")

    return {
        'statusCode': 200,
        'stopped': stopped,
        'skipped': skipped,
        'total_stopped': len(stopped)
    }