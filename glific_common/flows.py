"""Reading flows from Glific: the flow list and each flow's full definition, with credentials
blanked before it is returned."""
import json

from glific_common.api import GlificError, paged, post as glific_post
from glific_common.redact import redact_definition

FLOWS_QUERY = """
query flows($filter: FlowFilter, $opts: Opts) {
  flows(filter: $filter, opts: $opts) {
    id
    uuid
    name
    versionNumber
    flowType
    keywords
    lastPublishedAt
    lastChangedAt
    isActive
    tag { id label }
  }
}
"""

# Returns the full flow definition (nodes, actions, exits) as a JSON string
EXPORT_QUERY = """
query exportFlow($id: ID!) {
  exportFlow(id: $id) {
    exportData
    errors { key message }
  }
}
"""


def list_flows(token, filter=None, post=glific_post):
    """Every flow matching the filter (for example {"isActive": True}), without definitions."""
    return paged(FLOWS_QUERY, "flows", token, filter=filter, post=post)


def find_definition(export, flow_uuid):
    """export_data contains the flow plus any sub-flows it calls; pick the matching one."""
    for item in export.get("flows", []):
        definition = item.get("definition", item)
        if definition.get("uuid") == flow_uuid:
            return definition
    return None


def export_definition(flow_id, flow_uuid, token, post=glific_post):
    """(definition, number of credential values blanked) for one flow; Glific errors raise
    GlificError. The definition is {} when the export does not contain the flow."""
    result = post("/api", {"query": EXPORT_QUERY, "variables": {"id": flow_id}}, token)
    payload = (result.get("data") or {}).get("exportFlow") or {}
    if result.get("errors") or payload.get("errors"):
        raise GlificError(result.get("errors") or payload["errors"])
    export = payload.get("exportData") or payload.get("export_data") or {}
    if isinstance(export, str):
        export = json.loads(export)
    definition = find_definition(export, flow_uuid) or {}
    return definition, redact_definition(definition)
