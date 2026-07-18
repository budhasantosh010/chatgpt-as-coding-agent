def create_user(email: str) -> dict:
    return {"email": email.strip().lower()}


def find_user(users: list[dict], email: str) -> dict | None:
    wanted = email.strip().lower()
    return next((user for user in users if user["email"] == wanted), None)
