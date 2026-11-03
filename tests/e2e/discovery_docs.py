"""
Hand-trimmed Google API discovery documents, containing ONLY the methods
Invoice-Graph actually calls (gmail.users.getProfile, .messages.list,
.messages.get, .messages.attachments.get, oauth2.userinfo.get).

Sourced from the real, bundled discovery docs shipped with
google-api-python-client (googleapiclient/discovery_cache/documents/
gmail.v1.json and oauth2.v2.json), trimmed down to keep this stub small and
easy to reason about while remaining structurally valid enough for
googleapiclient's dynamic Resource builder to construct working request
objects against it.

`root_url` is injected at stub startup (see google_stub_app.py) so these
docs point back at the stub server itself rather than real Google.
"""


def gmail_v1_doc(root_url: str) -> dict:
    return {
        "kind": "discovery#restDescription",
        "id": "gmail:v1",
        "name": "gmail",
        "version": "v1",
        "rootUrl": root_url,
        "servicePath": "gmail/v1/",
        "basePath": "/gmail/v1/",
        "resources": {
            "users": {
                "methods": {
                    "getProfile": {
                        "id": "gmail.users.getProfile",
                        "path": "users/{userId}/profile",
                        "httpMethod": "GET",
                        "parameters": {
                            "userId": {"type": "string", "required": True, "location": "path"},
                        },
                        "parameterOrder": ["userId"],
                        "response": {"$ref": "Profile"},
                    }
                },
                "resources": {
                    "messages": {
                        "methods": {
                            "list": {
                                "id": "gmail.users.messages.list",
                                "path": "users/{userId}/messages",
                                "httpMethod": "GET",
                                "parameters": {
                                    "userId": {"type": "string", "required": True, "location": "path"},
                                    "q": {"type": "string", "location": "query"},
                                    "maxResults": {"type": "integer", "location": "query"},
                                },
                                "parameterOrder": ["userId"],
                                "response": {"$ref": "ListMessagesResponse"},
                            },
                            "get": {
                                "id": "gmail.users.messages.get",
                                "path": "users/{userId}/messages/{id}",
                                "httpMethod": "GET",
                                "parameters": {
                                    "userId": {"type": "string", "required": True, "location": "path"},
                                    "id": {"type": "string", "required": True, "location": "path"},
                                },
                                "parameterOrder": ["userId", "id"],
                                "response": {"$ref": "Message"},
                            },
                        },
                        "resources": {
                            "attachments": {
                                "methods": {
                                    "get": {
                                        "id": "gmail.users.messages.attachments.get",
                                        "path": "users/{userId}/messages/{messageId}/attachments/{id}",
                                        "httpMethod": "GET",
                                        "parameters": {
                                            "userId": {"type": "string", "required": True, "location": "path"},
                                            "messageId": {"type": "string", "required": True, "location": "path"},
                                            "id": {"type": "string", "required": True, "location": "path"},
                                        },
                                        "parameterOrder": ["userId", "messageId", "id"],
                                        "response": {"$ref": "MessagePartBody"},
                                    }
                                }
                            }
                        },
                    }
                },
            }
        },
        "schemas": {
            "Profile": {"type": "object"},
            "ListMessagesResponse": {"type": "object"},
            "Message": {"type": "object"},
            "MessagePartBody": {"type": "object"},
        },
    }


def oauth2_v2_doc(root_url: str) -> dict:
    return {
        "kind": "discovery#restDescription",
        "id": "oauth2:v2",
        "name": "oauth2",
        "version": "v2",
        "rootUrl": root_url,
        "servicePath": "",
        "basePath": "/",
        "resources": {
            "userinfo": {
                "methods": {
                    "get": {
                        "id": "oauth2.userinfo.get",
                        "path": "oauth2/v2/userinfo",
                        "httpMethod": "GET",
                        "response": {"$ref": "Userinfo"},
                    }
                }
            }
        },
        "schemas": {"Userinfo": {"type": "object"}},
    }
