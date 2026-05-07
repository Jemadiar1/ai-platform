export const tenantHeaderSchema = {
  type: "object",
  required: ["x-tenant-id"],
  properties: {
    "x-tenant-id": { type: "string", minLength: 1 },
  },
} as const;

