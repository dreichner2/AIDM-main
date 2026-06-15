const OPERATOR_TOOL_CAPABILITIES = new Set(['dm_authoring', 'dm_runtime_control', 'debug_read', 'admin_workspace'])

export function actorCapabilitiesAllowOperatorTools(capabilities: readonly string[] | null | undefined) {
  return Boolean(capabilities?.some((capability) => OPERATOR_TOOL_CAPABILITIES.has(capability)))
}
