"""The update agent release package: the agent that applies an OTA image, shipped in it.

One campaign, two halves. A consumer whose own agent is older than the bundle here
installs it, hands over to it, and that one applies the payload; a consumer already
running something at least as new ignores it.

One entry may carry several bundles. A bundle says what it is (`type`, opaque to the
image) and what it runs on (`architecture`), and a consumer takes only the one it
implements -- which is what lets a single image serve ECUs running different agents.

`otaclient_package` is the same concept for otaclient specifically and predates this.
"""

"""Update agent release package: the agent that applies an OTA image, shipped in it."""
