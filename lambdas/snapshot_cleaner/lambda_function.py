import boto3
from datetime import datetime, timedelta, timezone

def lambda_handler(event, context):
    ec2 = boto3.client('ec2', region_name='us-east-1')

    print("🔍 Scanning for old EBS snapshots...")

    # Step 1: Get all snapshots YOU own
    snapshots = ec2.describe_snapshots(
        OwnerIds=['self']
    )['Snapshots']

    print(f"📦 Total snapshots found: {len(snapshots)}")

    # Step 2: Get all AMIs you own (safety check)
    # We never delete snapshots that are backing an AMI
    images = ec2.describe_images(Owners=['self'])['Images']

    # Build a set of snapshot IDs that are in use by AMIs
    protected_snapshots = set()
    for image in images:
        for block in image.get('BlockDeviceMappings', []):
            ebs = block.get('Ebs', {})
            snap_id = ebs.get('SnapshotId')
            if snap_id:
                protected_snapshots.add(snap_id)

    print(f"🛡  Protected snapshots (linked to AMIs): {len(protected_snapshots)}")

    # Step 3: Define cutoff — 30 days ago
    cutoff = datetime.now(timezone.utc) - timedelta(days=30)

    deleted = []
    skipped_recent = []
    skipped_protected = []
    total_size_freed = 0

    # Step 4: Loop through snapshots and decide what to delete
    for snapshot in snapshots:
        snap_id    = snapshot['SnapshotId']
        start_time = snapshot['StartTime']
        size_gb    = snapshot['VolumeSize']
        desc       = snapshot.get('Description', 'No description')

        # Skip if protected by an AMI
        if snap_id in protected_snapshots:
            print(f"  🛡  {snap_id} — protected by AMI, skipping")
            skipped_protected.append(snap_id)
            continue

        # Skip if newer than 30 days
        if start_time > cutoff:
            age_days = (datetime.now(timezone.utc) - start_time).days
            print(f"  🕐  {snap_id} — only {age_days} days old, skipping")
            skipped_recent.append(snap_id)
            continue

        # Safe to delete
        age_days = (datetime.now(timezone.utc) - start_time).days
        print(f"  🗑  {snap_id} — {age_days} days old, {size_gb}GB — DELETING")

        try:
            ec2.delete_snapshot(SnapshotId=snap_id)
            deleted.append(snap_id)
            total_size_freed += size_gb

        except Exception as e:
            # Some snapshots can't be deleted (e.g. in use by a volume)
            print(f"  ❌  {snap_id} — could not delete: {str(e)}")

    # Step 5: Summary
    print(f"\n📊 Summary:")
    print(f"  Deleted   : {len(deleted)} snapshots")
    print(f"  Freed     : {total_size_freed} GB")
    print(f"  Protected : {len(skipped_protected)} snapshots")
    print(f"  Too recent: {len(skipped_recent)} snapshots")

    return {
        'statusCode': 200,
        'deleted_count': len(deleted),
        'deleted_snapshots': deleted,
        'storage_freed_gb': total_size_freed,
        'skipped_protected': len(skipped_protected),
        'skipped_recent': len(skipped_recent)
    }

