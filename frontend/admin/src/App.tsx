import { BrowserRouter, Navigate, Outlet, Route, Routes, useNavigate, NavLink } from 'react-router-dom';
import { BookOpen, Users, LogOut } from 'lucide-react';
import LoginPage from './pages/LoginPage';
import CoursesPage from './pages/CoursesPage';
import RosterPage from './pages/RosterPage';
import UsersPage from './pages/UsersPage';
import UserDetailPage from './pages/UserDetailPage';
import { ThemeToggle } from './components/ThemeToggle';

function RequireAdmin() {
  const token = localStorage.getItem('token');
  if (!token) return <Navigate to="/login" replace />;
  return <Outlet />;
}

function AdminLayout() {
  const navigate = useNavigate();

  function logout() {
    localStorage.removeItem('token');
    navigate('/login');
  }

  const linkClass = ({ isActive }: { isActive: boolean }) =>
    `flex items-center gap-3 px-4 py-2.5 rounded-lg text-sm font-medium transition-colors ${
      isActive ? 'bg-accent text-accent-contrast' : 'text-secondary hover:bg-surface-sunken hover:text-primary'
    }`;

  return (
    <div className="flex min-h-screen">
      <aside className="w-56 shrink-0 bg-surface-raised border-r border-border flex flex-col">
        <div className="px-6 py-5 border-b border-border flex items-center justify-between">
          <h1 className="text-lg font-bold text-primary">QnA Admin</h1>
          <ThemeToggle />
        </div>
        <nav className="flex-1 p-3 space-y-1">
          <NavLink to="/courses" className={linkClass}>
            <BookOpen size={16} /> Courses
          </NavLink>
          <NavLink to="/users" className={linkClass}>
            <Users size={16} /> Users
          </NavLink>
        </nav>
        <div className="p-3 border-t border-border">
          <button
            onClick={logout}
            className="flex items-center gap-3 px-4 py-2.5 rounded-lg text-sm font-medium text-secondary hover:bg-surface-sunken hover:text-primary w-full transition-colors"
          >
            <LogOut size={16} /> Logout
          </button>
        </div>
      </aside>

      <main className="flex-1 overflow-auto">
        <Outlet />
      </main>
    </div>
  );
}

export default function App() {
  return (
    <BrowserRouter basename={import.meta.env.BASE_URL}>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route element={<RequireAdmin />}>
          <Route element={<AdminLayout />}>
            <Route path="/courses" element={<CoursesPage />} />
            <Route path="/courses/:courseId/roster" element={<RosterPage />} />
            <Route path="/users" element={<UsersPage />} />
            <Route path="/users/:userId" element={<UserDetailPage />} />
          </Route>
        </Route>
        <Route path="*" element={<Navigate to="/courses" replace />} />
      </Routes>
    </BrowserRouter>
  );
}
