/**
 * Layout principal del dashboard.
 * 
 * Este layout envuelve todas las páginas del dashboard con:
 * - Autenticación de Clerk (solo usuarios logueados pueden acceder)
 * - Sidebar de navegación
 * - Header con información del usuario
 * - Mensajes de error globales
 */

import { ClerkProvider, SignedIn, SignedOut, SignInButton, UserButton } from "@clerk/nextjs";
import { redirect } from "next/navigation";
import { currentUser } from "@clerk/nextjs/server";
import Sidebar from "./components/Sidebar";

export default async function DashboardLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  // Verificar que el usuario está autenticado
  const user = await currentUser();
  if (!user) {
    redirect("/login");
  }
  
  return (
    <ClerkProvider>
      <div className="min-h-screen bg-gray-50">
        {/* Sidebar */}
        <Sidebar />
        
        {/* Main Content */}
        <div className="lg:pl-64">
          {/* Header */}
          <header className="sticky top-0 z-10 flex h-16 flex-shrink-0 bg-white shadow">
            <div className="flex flex-1 items-center justify-between px-4">
              <h1 className="text-lg font-semibold text-gray-900">
                NeuralCrew Labs
              </h1>
              
              <div className="flex items-center gap-4">
                <SignedIn>
                  <UserButton afterSignOutUrl="/" />
                </SignedIn>
                <SignedOut>
                  <SignInButton />
                </SignedOut>
              </div>
            </div>
          </header>
          
          {/* Content */}
          <main className="py-6">
            <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
              {children}
            </div>
          </main>
        </div>
      </div>
    </ClerkProvider>
  );
}
