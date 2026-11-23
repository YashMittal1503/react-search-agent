import { ClientApp } from "@/components/ClientApp";

/** The only route: the chat app (threads are selected with `?t=<id>`, not separate routes). */
export default function Page() {
  return <ClientApp />;
}
