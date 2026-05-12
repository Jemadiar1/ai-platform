import Fastify from "fastify";

const server = Fastify({ logger: true });

server.get("/health", async () => ({ status: "ok", service: "api-gateway" }));

server.get("/api/v1/ping", async () => ({
  data: { pong: true },
  error: null,
  meta: { version: "v1" },
}));

const port = Number(process.env.PORT ?? 4000);

server.listen({ port, host: "0.0.0.0" }).catch((error) => {
  server.log.error(error);
  process.exit(1);
});

