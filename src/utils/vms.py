import os
import subprocess
import argparse
import json
from datetime import datetime
import shutil


VMS_DIR = ".vms"
INDEX_FILE = os.path.join(VMS_DIR, "index.json")

class VMS:
    def __init__(self, directory):
        self.directory = directory

    def init_vms(self):
        """Initialize the version management system"""
        os.chdir(self.directory)
        # Create version management directory
        if not os.path.exists(VMS_DIR):
            os.makedirs(VMS_DIR)
        
        subprocess.run(["git", "config", "--global", "--add", "safe.directory", self.directory], check=True)

        # Initialize Git repository (if not exists)
        if not os.path.exists(os.path.join(VMS_DIR, ".git")):
            subprocess.run(["git", "init", self.directory], check=True)
        
        # Initialize index file
        if not os.path.exists(INDEX_FILE):
            with open(INDEX_FILE, "w") as f:
                json.dump({
                "current": -1,
                "snapshots": []
            }, f, indent=2)
        
        git_ignore_path = os.path.join(self.directory, ".gitignore")
        if not os.path.exists(git_ignore_path):
            with open(git_ignore_path, "w") as f:
                f.write(".vms\n")
        
        print(f"Initialized version management system in {self.directory}")

    def delete_vms(self):
        """Delete the version management system"""
        os.chdir(self.directory)
        
        # Delete version management directory
        if os.path.exists(VMS_DIR):
            shutil.rmtree(VMS_DIR)
        
        # Delete Git repository
        if os.path.exists(os.path.join(self.directory, ".git")):
            shutil.rmtree(os.path.join(self.directory, ".git"))

        print(f"Deleted version management system in {self.directory}")

    def create_snapshot(self, message=None):
        """Create a new snapshot"""
        os.chdir(self.directory)
        
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        # Generate snapshot message
        if not message:
            message = f"Snapshot at {timestamp}"
        else:
            message = f"{message} Snapshot at {timestamp}"
        
        # Check index file
        if not os.path.exists(INDEX_FILE):
            raise FileNotFoundError("Version system not initialized. Run 'init' first.")
        
        # Read index data
        with open(INDEX_FILE, "r") as f:
            index_data = json.load(f)
        
        # Add all files to Git
        import time
        for _ in range(10):
            result = subprocess.run(["git", "-C", self.directory, "add", "."], capture_output=True)
            if result.returncode == 0:
                break
            # Remove index.lock if it exists to prevent deadlocks
            lock_file = os.path.join(self.directory, ".git", "index.lock")
            if os.path.exists(lock_file):
                try:
                    os.remove(lock_file)
                except OSError:
                    pass
            time.sleep(1)
        
        # Commit changes
        for _ in range(10):
            result = subprocess.run(
                ["git", "-C", self.directory, "commit", "-m", message],
                capture_output=True,
                text=True
            )
            if "nothing to commit" in result.stdout:
                return 0, "0"
            if result.returncode == 0:
                break
            # Remove index.lock if it exists
            lock_file = os.path.join(self.directory, ".git", "index.lock")
            if os.path.exists(lock_file):
                try:
                    os.remove(lock_file)
                except OSError:
                    pass
            time.sleep(1)
        
        # Get commit hash
        commit_hash = subprocess.check_output(
            ["git", "-C", self.directory, "rev-parse", "HEAD"],
            text=True
        ).strip()[:7]
        
        # Update index
        snapshot = {
            "id": len(index_data["snapshots"]),
            "hash": commit_hash,
            "message": message,
            "timestamp": datetime.now().isoformat()
        }
        
        # Truncate records after current snapshot
        current_index = index_data["current"]
        if current_index < len(index_data["snapshots"]) - 1:
            index_data["snapshots"] = index_data["snapshots"][:current_index + 1]
        
        # Add new snapshot
        index_data["snapshots"].append(snapshot)
        index_data["current"] = len(index_data["snapshots"]) - 1
        
        # Save index
        with open(INDEX_FILE, "w") as f:
            json.dump(index_data, f, indent=2)
        
        print(f"Created snapshot #{snapshot['id']}: {commit_hash} - {message}")
        return snapshot['id'], commit_hash

    def list_snapshots(self):
        """List all snapshots"""
        os.chdir(self.directory)
        
        if not os.path.exists(INDEX_FILE):
            raise FileNotFoundError("Version system not initialized. Run 'init' first.")
        
        with open(INDEX_FILE, "r") as f:
            index_data = json.load(f)
        
        print("\nSnapshot History:")
        print("ID  | Status | Hash   | Message")
        print("-" * 50)
        
        for i, snap in enumerate(index_data["snapshots"]):
            status = "->" if i == index_data["current"] else "  "
            print(f"{snap['id']:3} | {status}     | {snap['hash']} | {snap['message']}")
        
        print(f"\nCurrent position: {index_data['current']}/{len(index_data['snapshots']) - 1}")

    def restore_snapshot(self, target_id):
        """Restore to the specified snapshot"""
        os.chdir(self.directory)
        
        if not os.path.exists(INDEX_FILE):
            raise FileNotFoundError("Version system not initialized. Run 'init' first.")
        
        with open(INDEX_FILE, "r") as f:
            index_data = json.load(f)
        
        # Find the target snapshot
        target_snap = next((s for s in index_data["snapshots"] if s["id"] == target_id), None)
        if not target_snap:
            raise ValueError(f"Snapshot #{target_id} not found")
        
        # Reset working directory to the target version
        subprocess.run([
            "git", "-C", self.directory, "checkout", target_snap["hash"], "--", "."
        ], check=True)
        
        # Update current pointer
        index_data["current"] = target_id
        with open(INDEX_FILE, "w") as f:
            json.dump(index_data, f, indent=2)
        
        print(f"Restored to snapshot #{target_id}: {target_snap['message']}")

    def move_snapshot(self, direction):
        """Move forward/backward to the adjacent snapshot"""
        os.chdir(self.directory)
        
        if not os.path.exists(INDEX_FILE):
            raise FileNotFoundError("Version system not initialized. Run 'init' first.")
        
        with open(INDEX_FILE, "r") as f:
            index_data = json.load(f)
        
        current = index_data["current"]
        new_index = current + (1 if direction == "forward" else -1)
        
        if new_index < 0 or new_index >= len(index_data["snapshots"]):
            print(f"Cannot move {direction} from position {current}")
            return
        
        self.restore_snapshot(new_index)

def main():
    parser = argparse.ArgumentParser(description="Directory Version Management System")
    parser.add_argument("directory", help="Target directory")
    subparsers = parser.add_subparsers(dest="command", required=True)
    
    init_parser = subparsers.add_parser("init", help="Initialize version system")
    
    snap_parser = subparsers.add_parser("snapshot", help="Create new snapshot")
    snap_parser.add_argument("-m", "--message", help="Snapshot message")

    list_parser = subparsers.add_parser("list", help="List snapshots")

    restore_parser = subparsers.add_parser("restore", help="Restore to snapshot")
    restore_parser.add_argument("snapshot_id", type=int, help="Snapshot ID")
    
    back_parser = subparsers.add_parser("back", help="Move to previous snapshot")

    fwd_parser = subparsers.add_parser("forward", help="Move to next snapshot")
    
    args = parser.parse_args()
    
    vms = VMS(args.directory)
    try:
        if args.command == "init":
            vms.init_vms()
        elif args.command == "snapshot":
            vms.create_snapshot(args.message)
        elif args.command == "list":
            vms.list_snapshots()
        elif args.command == "restore":
            vms.restore_snapshot(args.snapshot_id)
        elif args.command == "back":
            vms.move_snapshot("backward")
        elif args.command == "forward":
            vms.move_snapshot("forward")
    except Exception as e:
        print(f"Error: {str(e)}")

if __name__ == "__main__":
    main()