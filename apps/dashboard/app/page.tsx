/**
 * App Router - Root
 * 
 * Esta página redirige a /dashboard si el usuario está autenticado,
 * o a /login si no.
 */

import { redirect } from "next/navigation";
import { currentUser } from "@clerk/nextjs/server";

export default async function Home() {
  const user = await currentUser();
  
  if (user) {
    redirect("/dashboard");
  }
  
  redirect("/login");
}
