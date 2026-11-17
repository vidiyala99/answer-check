Here is how to fetch a user and update their name with the WorkOS Python SDK:

```python
from workos import WorkOSClient

client = WorkOSClient(api_key="sk_test_...", client_id="client_...")

user = client.user_management.get_user(id_="user_01H...")
client.user_management.update_user(user_id=user.id, first_name="Ada")
```
