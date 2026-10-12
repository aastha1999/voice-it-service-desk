"""Fictional company: Northwind Labs. All people, devices, and serials are made up."""

EMPLOYEES = [
    {"id": "E100", "name": "Priya Shah", "email": "priya.shah@northwind.example", "department": "Finance"},
    {"id": "E101", "name": "Marcus Lee", "email": "marcus.lee@northwind.example", "department": "Engineering"},
    {"id": "E102", "name": "Jordan Rivera", "email": "jordan.rivera@northwind.example", "department": "Sales"},
    {"id": "E103", "name": "Aiko Tanaka", "email": "aiko.tanaka@northwind.example", "department": "People Ops"},
]

DEVICES = [
    {"id": "DEV-001", "asset_tag": "NW-1042", "serial": "C02XK4F2K", "model": "MacBook Pro 14-inch (M3)",
     "os": "macOS", "os_version": "15.3", "owner_id": "E100", "status": "active", "online": 1,
     "last_check_in": "2026-10-12T08:41:00Z", "disk_encrypted": 1},
    {"id": "DEV-002", "asset_tag": "NW-1043", "serial": "F17ZQ8RT", "model": "iPhone 15",
     "os": "iOS", "os_version": "18.2", "owner_id": "E100", "status": "active", "online": 1,
     "last_check_in": "2026-10-12T09:02:00Z", "disk_encrypted": 1},
    {"id": "DEV-003", "asset_tag": "NW-2177", "serial": "7XKD2Q3", "model": "Dell Latitude 7440",
     "os": "Windows", "os_version": "11 23H2", "owner_id": "E101", "status": "active", "online": 1,
     "last_check_in": "2026-10-12T07:15:00Z", "disk_encrypted": 1},
    {"id": "DEV-004", "asset_tag": "NW-3051", "serial": "C02ZP9LMN", "model": "MacBook Air 13-inch (M2)",
     "os": "macOS", "os_version": "14.6", "owner_id": "E102", "status": "active", "online": 0,
     "last_check_in": "2026-10-09T17:30:00Z", "disk_encrypted": 1},
    {"id": "DEV-005", "asset_tag": "NW-0999", "serial": "PF3A1B2C", "model": "ThinkPad T14",
     "os": "Windows", "os_version": "10 22H2", "owner_id": "E103", "status": "retired", "online": 0,
     "last_check_in": "2025-12-01T12:00:00Z", "disk_encrypted": 1},
]
