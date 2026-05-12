/**
 * Componente Sidebar - Barra lateral de navegación
 * 
 * Este componente muestra:
 * - Logo de NeuralCrew Labs
 * - Links a las diferentes secciones del dashboard
 * - Estado de la suscripción del tenant
 * - Información del plan actual
 * 
 * En pantallas pequeñas se colapsa. En pantallas grandes siempre está visible.
 */

"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  LayoutDashboard,
  MessageSquare,
  PenTool,
  Share2,
  Users,
  Target,
  BarChart3,
  Globe,
  Settings,
  CreditCard,
} from "lucide-react";

const navigation = [
  { name: "Dashboard", href: "/dashboard", icon: LayoutDashboard },
  { name: "Connect", href: "/dashboard/connect", icon: MessageSquare },
  { name: "Content", href: "/dashboard/content", icon: PenTool },
  { name: "Social", href: "/dashboard/social", icon: Share2 },
  { name: "Leads", href: "/dashboard/leads", icon: Users },
  { name: "Ads", href: "/dashboard/ads", icon: Target },
  { name: "Analytics", href: "/dashboard/analytics", icon: BarChart3 },
  { name: "Website", href: "/dashboard/website", icon: Globe },
];

const secondary = [
  { name: "Settings", href: "/dashboard/settings", icon: Settings },
  { name: "Billing", href: "/dashboard/billing", icon: CreditCard },
];

export default function Sidebar() {
  const pathname = usePathname();
  
  return (
    <div className="hidden lg:fixed lg:inset-y-0 lg:z-50 lg:flex lg:w-64 lg:flex-col">
      <div className="flex flex-col flex-grow border-r border-gray-200 bg-white pt-5">
        {/* Logo */}
        <div className="flex items-center flex-shrink-0 px-4">
          <h2 className="text-lg font-bold text-gray-900">
            NeuralCrew Labs
          </h2>
        </div>
        
        {/* Navigation */}
        <nav className="mt-5 flex-grow space-y-1 px-2">
          {navigation.map((item) => {
            const isActive = pathname === item.href;
            return (
              <Link
                key={item.name}
                href={item.href}
                className={`
                  group flex items-center px-2 py-2 text-sm font-medium rounded-md
                  ${isActive
                    ? "bg-gray-100 text-gray-900"
                    : "text-gray-600 hover:bg-gray-50 hover:text-gray-900"
                  }
                `}
              >
                <item.icon className="mr-3 h-5 w-5 flex-shrink-0" />
                {item.name}
              </Link>
            );
          })}
        </nav>
        
        {/* Secondary Navigation */}
        <div className="mt-auto pb-4">
          <div className="border-t border-gray-200 pt-4">
            {secondary.map((item) => {
              const isActive = pathname === item.href;
              return (
                <Link
                  key={item.name}
                  href={item.href}
                  className={`
                    group flex items-center px-2 py-2 text-sm font-medium rounded-md
                    ${isActive
                      ? "bg-gray-100 text-gray-900"
                      : "text-gray-600 hover:bg-gray-50 hover:text-gray-900"
                    }
                  `}
                >
                  <item.icon className="mr-3 h-5 w-5 flex-shrink-0" />
                  {item.name}
                </Link>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
}
