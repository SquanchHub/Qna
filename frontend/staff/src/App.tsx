import { BrowserRouter, Navigate, NavLink, Outlet, Route, Routes, useNavigate } from 'react-router-dom';
import { Database, Layers, LogOut, MessageSquare, Tags } from 'lucide-react';
import { CourseProvider, useCourse } from './lib/CourseContext';
import { ThemeToggle } from './components/ThemeToggle';
import LoginPage from './pages/LoginPage';
import QuestionsPage from './pages/QuestionsPage';
import AskQuestionPage from './pages/AskQuestionPage';
import QuestionDetailPage from './pages/QuestionDetailPage';
import CategoriesPage from './pages/CategoriesPage';
import ResourcesPage from './pages/ResourcesPage';
import ProfilesPage from './pages/ProfilesPage';

function RequireAuth() {
  const token = localStorage.getItem('token');
  if (!token) return <Navigate to="/login" replace />;
  return <Outlet />;
}

function Layout() {
  const navigate = useNavigate();
  const { courses, courseId, setCourseId, refresh } = useCourse();

  function logout() {
    localStorage.removeItem('token');
    void refresh(); // clears course state so it doesn't leak into the next login
    navigate('/login');
  }

  const linkClass = ({ isActive }: { isActive: boolean }) =>
    `flex items-center gap-1.5 text-sm ${isActive ? 'text-accent' : 'text-secondary hover:text-primary'}`;

  return (
    <div className="min-h-screen">
      <header className="border-b border-border bg-surface-raised">
        <div className="max-w-3xl mx-auto px-8 py-4 flex items-center justify-between">
          <div className="flex items-center gap-6">
            <span className="flex items-center gap-2 text-primary font-bold">
              <MessageSquare size={20} /> Course Q&amp;A — Staff
            </span>
            <nav className="flex items-center gap-4">
              <NavLink to="/questions" className={linkClass}>
                Questions
              </NavLink>
              <NavLink to="/categories" className={linkClass}>
                <Tags size={14} /> Categories
              </NavLink>
              <NavLink to="/resources" className={linkClass}>
                <Database size={14} /> Resources
              </NavLink>
              <NavLink to="/profiles" className={linkClass}>
                <Layers size={14} /> Profiles
              </NavLink>
            </nav>
          </div>
          <div className="flex items-center gap-3">
            {courses.length > 1 && (
              <label className="flex items-center gap-1.5 text-sm text-muted">
                Course:
                <select
                  value={courseId ?? ''}
                  onChange={(e) => setCourseId(Number(e.target.value))}
                  className="rounded-lg border border-border-strong bg-surface-sunken px-2 py-1.5 text-sm text-primary"
                >
                  {courses.map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.name} ({c.semester})
                    </option>
                  ))}
                </select>
              </label>
            )}
            <ThemeToggle />
            <button
              onClick={logout}
              className="flex items-center gap-1.5 text-sm text-secondary hover:text-primary"
            >
              <LogOut size={16} /> Logout
            </button>
          </div>
        </div>
      </header>
      <Outlet />
    </div>
  );
}

export default function App() {
  return (
    <BrowserRouter basename={import.meta.env.BASE_URL}>
      <CourseProvider>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route element={<RequireAuth />}>
            <Route element={<Layout />}>
              <Route path="/questions" element={<QuestionsPage />} />
              <Route path="/questions/new" element={<AskQuestionPage />} />
              <Route path="/questions/:questionId" element={<QuestionDetailPage />} />
              <Route path="/categories" element={<CategoriesPage />} />
              <Route path="/resources" element={<ResourcesPage />} />
              <Route path="/profiles" element={<ProfilesPage />} />
            </Route>
          </Route>
          <Route path="*" element={<Navigate to="/questions" replace />} />
        </Routes>
      </CourseProvider>
    </BrowserRouter>
  );
}
