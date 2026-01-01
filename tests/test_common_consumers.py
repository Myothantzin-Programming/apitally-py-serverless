from apitally_serverless.common.consumers import ApitallyConsumer, _seen_consumer_hashes


def test_consumer_deduplication():
    _seen_consumer_hashes.clear()

    # First consumer with name/group should keep them
    consumer = ApitallyConsumer(identifier="user1", name="John", group="Admin")
    assert consumer.name == "John"
    assert consumer.group == "Admin"

    # Same consumer again should have name/group cleared
    consumer = ApitallyConsumer(identifier="user1", name="John", group="Admin")
    assert consumer.name is None
    assert consumer.group is None

    # Different consumer should keep name/group
    consumer = ApitallyConsumer(identifier="user2", name="Jane", group="Admin")
    assert consumer.name == "Jane"
    assert consumer.group == "Admin"
