from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class PairNodeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid",hide_input_in_errors=True)
    node_key: str = Field(pattern=r'^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$')
    display_name: str = Field(min_length=1,max_length=128)
    expires_in_days: int = Field(default=30,ge=1,le=365)


class RotateNodeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid",hide_input_in_errors=True)
    expires_in_days: int = Field(default=30,ge=1,le=365)


class CapabilityRequest(BaseModel):
    model_config = ConfigDict(extra="forbid",hide_input_in_errors=True)
    project_id: UUID
    capability: Literal['harness','source_acquisition','issue_executor']
    constraints: dict[str, Any] = Field(default_factory=dict)
    policy_version: str = Field(default='operator-v1',min_length=1,max_length=64)


    @model_validator(mode="after")
    def controlled_scope(self):
        if self.capability=="harness":
            import re

            if set(self.constraints) - {"interactive_host_adapters"}:
                raise ValueError("Harness project scope has no credential or arbitrary configuration fields")
            adapters = self.constraints.get("interactive_host_adapters")
            if adapters is not None and (
                not isinstance(adapters, list) or not 1 <= len(adapters) <= 16
                or any(not isinstance(item, str)
                       or not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_./-]{0,127}", item)
                       for item in adapters)
                or len(set(adapters)) != len(adapters)
            ):
                raise ValueError("Interactive execution requires a bounded host adapter allowlist")
        elif self.capability=="source_acquisition":
            from hypertest.connector.source import validate_origin
            if set(self.constraints)-{"allowed_origins","policy_version"}:
                raise ValueError("Source scope accepts only approved origin references")
            origins=self.constraints.get("allowed_origins")
            if not isinstance(origins,list) or not 1<=len(origins)<=100:
                raise ValueError("Source scope requires a bounded origin allowlist")
            for origin in origins:
                validate_origin(origin)
            if self.constraints.get("policy_version",self.policy_version)!=self.policy_version:
                raise ValueError("Source policy version must match the granted scope")
        else:
            from urllib.parse import urlsplit
            expected={"integration_id","base_url","gitlab_project_id","assignee_ids"}
            if set(self.constraints)!=expected:
                raise ValueError("Issue scope requires only integration, project and assignee references")
            value=self.constraints
            if not isinstance(value["base_url"],str) or not 1<=len(value["base_url"])<=2048 or any(c.isspace() for c in value["base_url"]):
                raise ValueError("Issue scope requires a credential-free HTTPS origin")
            target=urlsplit(value["base_url"])
            if (target.scheme!="https" or not target.hostname or target.username is not None
                    or target.query or target.fragment or ".." in target.path.split("/")):
                raise ValueError("Issue scope requires a credential-free HTTPS origin")
            if (not isinstance(value["integration_id"],str) or not 1<=len(value["integration_id"])<=128
                    or type(value["gitlab_project_id"]) is not int or value["gitlab_project_id"]<1
                    or not isinstance(value["assignee_ids"],list) or not 1<=len(value["assignee_ids"])<=100
                    or any(type(i) is not int or i<1 for i in value["assignee_ids"])):
                raise ValueError("Issue project and assignee scope is invalid")
        return self
