from datetime import datetime

users = [
    {"id": 1, "username": "skye", "password": "123456"},
    {"id": 2, "username": "alex", "password": "123456"},
]

groups = [
    {
        "id": 1,
        "name": "San Diego Charters",
        "description": "Discussions about charter fishing trips in San Diego",
    },
    {
        "id": 2,
        "name": "LA Shore Fishing",
        "description": "Local shore fishing reports and tips in Los Angeles",
    },
    {
        "id": 3,
        "name": "Tackle Tips",
        "description": "Talk about rods, reels, bait, and tackle setups",
    },
    {
        "id": 4,
        "name": "Yellowtail Reports",
        "description": "Share yellowtail catches, methods, and trip reports",
    },
    {
        "id": 5,
        "name": "Beginner Questions",
        "description": "A place for new anglers to ask beginner-friendly questions",
    },
]

memberships = [
    {"user_id": 1, "group_id": 2},
    {"user_id": 1, "group_id": 5},
]

public_posts = [
    {
        "id": 1,
        "title": "First time catching yellowtail",
        "content": "Yesterday I went on a charter near San Diego and tried blue iron for the first time. Still learning how fast I should retrieve it.",
        "author": "alex",
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M"),
    },
    {
        "id": 2,
        "title": "Need beginner advice",
        "content": "I’m new to shore fishing in LA. What setup would you recommend for someone just starting out?",
        "author": "skye",
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M"),
    },
]

group_messages = [
    {
        "id": 1,
        "group_id": 2,
        "content": "Anyone been fishing Redondo recently? How was the bite?",
        "author": "skye",
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M"),
    },
    {
        "id": 2,
        "group_id": 1,
        "content": "Thinking about booking a charter next weekend. Any recent yellowtail reports?",
        "author": "alex",
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M"),
    },
]