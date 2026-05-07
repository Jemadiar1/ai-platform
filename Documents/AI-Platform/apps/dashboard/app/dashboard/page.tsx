/**
 * Página principal del Dashboard
 * 
 * Muestra:
 * - Estadísticas generales (tareas, uso, costos)
 * - Tareas recientes con su estado
 * - Acceso rápido a módulos
 * - Gráficos de uso (placeholder)
 * 
 * Se conecta al backend en http://localhost:4000/api/v1/
 */

"use client";

import { useEffect, useState } from "react";
import {
  CheckCircle,
  Clock,
  AlertCircle,
  TrendingUp,
  MessageSquare,
  PenTool,
  Share2,
  Users,
  Target,
  BarChart3,
  Globe,
} from "lucide-react";

interface Task {
  id: string;
  module: string;
  status: string;
  created_at: string;
  result?: any;
}

interface UsageStats {
  total_tasks: number;
  completed_tasks: number;
  failed_tasks: number;
  tokens_used: number;
  estimated_cost: number;
}

export default function DashboardPage() {
  const [tasks, setTasks] = useState<Task[]>([]);
  const [usage, setUsage] = useState<UsageStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchDashboardData();
  }, []);

  async function fetchDashboardData() {
    try {
      // Fetch tasks
      const tasksResponse = await fetch("http://localhost:4000/api/v1/tasks?limit=5");
      if (tasksResponse.ok) {
        const tasksData = await tasksResponse.json();
        setTasks(tasksData);
      }
      
      // Fetch usage stats (placeholder)
      const usageResponse = await fetch("http://localhost:4000/api/v1/usage");
      if (usageResponse.ok) {
        const usageData = await usageResponse.json();
        setUsage(usageData);
      }
    } catch (err) {
      setError("Error al cargar datos del dashboard");
      console.error(err);
    } finally {
      setLoading(false);
    }
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-gray-900"></div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="bg-red-50 border border-red-200 rounded-lg p-4">
        <p className="text-red-800">{error}</p>
      </div>
    );
  }

  return (
    <div>
      <h1 className="text-2xl font-bold text-gray-900 mb-6">
        Dashboard
      </h1>

      {/* Stats Cards */}
      <div className="grid grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-4 mb-8">
        <StatCard
          title="Tareas Completadas"
          value={usage?.completed_tasks || 0}
          icon={CheckCircle}
          color="green"
        />
        <StatCard
          title="Tareas en Progreso"
          value={usage?.total_tasks - (usage?.completed_tasks || 0) - (usage?.failed_tasks || 0)}
          icon={Clock}
          color="blue"
        />
        <StatCard
          title="Tokens Usados"
          value={usage?.tokens_used?.toLocaleString() || "0"}
          icon={TrendingUp}
          color="purple"
        />
        <StatCard
          title="Costo Estimado"
          value={`$${usage?.estimated_cost?.toFixed(2) || "0.00"}`}
          icon={Target}
          color="orange"
        />
      </div>

      {/* Quick Access Modules */}
      <div className="mb-8">
        <h2 className="text-lg font-semibold text-gray-900 mb-4">Módulos</h2>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <ModuleCard
            name="Connect"
            description="WhatsApp, Voz, Chat"
            icon={MessageSquare}
            href="/dashboard/connect"
          />
          <ModuleCard
            name="Content"
            description="Generación de contenido"
            icon={PenTool}
            href="/dashboard/content"
          />
          <ModuleCard
            name="Social"
            description="Redes sociales"
            icon={Share2}
            href="/dashboard/social"
          />
          <ModuleCard
            name="Leads"
            description="Captura de leads"
            icon={Users}
            href="/dashboard/leads"
          />
        </div>
      </div>

      {/* Recent Tasks */}
      <div className="bg-white shadow rounded-lg">
        <div className="px-6 py-4 border-b border-gray-200">
          <h2 className="text-lg font-semibold text-gray-900">
            Tareas Recientes
          </h2>
        </div>
        <div className="divide-y divide-gray-200">
          {tasks.length === 0 ? (
            <div className="px-6 py-8 text-center text-gray-500">
              No hay tareas recientes
            </div>
          ) : (
            tasks.map((task) => (
              <TaskRow key={task.id} task={task} />
            ))
          )}
        </div>
      </div>
    </div>
  );
}

/**
 * Componente de tarjeta de estadísticas
 */
function StatCard({
  title,
  value,
  icon: Icon,
  color,
}: {
  title: string;
  value: string | number;
  icon: any;
  color: string;
}) {
  const colorClasses: Record<string, string> = {
    green: "bg-green-500",
    blue: "bg-blue-500",
    purple: "bg-purple-500",
    orange: "bg-orange-500",
  };

  return (
    <div className="bg-white overflow-hidden shadow rounded-lg">
      <div className="p-5">
        <div className="flex items-center">
          <div className={`flex-shrink-0 ${colorClasses[color] || "bg-gray-500"} rounded-md p-3`}>
            <Icon className="h-6 w-6 text-white" />
          </div>
          <div className="ml-5 w-0 flex-1">
            <dl>
              <dt className="text-sm font-medium text-gray-500 truncate">
                {title}
              </dt>
              <dd className="text-2xl font-semibold text-gray-900">
                {value}
              </dd>
            </dl>
          </div>
        </div>
      </div>
    </div>
  );
}

/**
 * Componente de tarjeta de módulo
 */
function ModuleCard({
  name,
  description,
  icon: Icon,
  href,
}: {
  name: string;
  description: string;
  icon: any;
  href: string;
}) {
  return (
    <Link
      href={href}
      className="bg-white overflow-hidden shadow rounded-lg hover:shadow-md transition-shadow"
    >
      <div className="p-5">
        <div className="flex items-center">
          <div className="flex-shrink-0 bg-indigo-500 rounded-md p-3">
            <Icon className="h-6 w-6 text-white" />
          </div>
          <div className="ml-4">
            <h3 className="text-lg font-medium text-gray-900">{name}</h3>
            <p className="text-sm text-gray-500">{description}</p>
          </div>
        </div>
      </div>
    </Link>
  );
}

/**
 * Componente de fila de tarea
 */
function TaskRow({ task }: { task: Task }) {
  const statusColors: Record<string, string> = {
    pending: "bg-yellow-100 text-yellow-800",
    running: "bg-blue-100 text-blue-800",
    completed: "bg-green-100 text-green-800",
    failed: "bg-red-100 text-red-800",
  };

  const statusLabels: Record<string, string> = {
    pending: "Pendiente",
    running: "En progreso",
    completed: "Completada",
    failed: "Fallida",
  };

  return (
    <div className="px-6 py-4 flex items-center justify-between">
      <div className="flex items-center">
        <span className="text-sm font-medium text-gray-900">
          {task.module}
        </span>
        <span className="ml-2 text-sm text-gray-500">
          {new Date(task.created_at).toLocaleDateString()}
        </span>
      </div>
      <span
        className={`px-2 inline-flex text-xs leading-5 font-semibold rounded-full ${
          statusColors[task.status] || "bg-gray-100 text-gray-800"
        }`}
      >
        {statusLabels[task.status] || task.status}
      </span>
    </div>
  );
}
