/**
 * ============================================================================
 * MAIN APP COMPONENT - LearnAI Platform
 * ============================================================================
 * 
 * This is the root component that manages the overall application structure,
 * routing, and layout. It handles:
 * - Authentication state
 * - View routing between different screens
 * - Layout with sidebar navigation
 * - Global providers
 * 
 * ARCHITECTURE:
 * - Uses React hooks for state management
 * - Context providers wrap the entire app
 * - Conditional rendering based on auth state
 * - View-based routing (simpler than React Router for this MVP)
 * 
 * TO ADD NEW VIEWS:
 * 1. Import the component
 * 2. Add to the views object in MainLayout
 * 3. Add navigation item in Sidebar
 * 
 * ============================================================================
 */

import { useState } from 'react';
import { AuthProvider, useAuth, AppProvider } from '@/contexts';
import { Toaster } from '@/components/ui/sonner';
import { LoginScreen } from '@/sections/auth/LoginScreen';
import { Sidebar } from '@/sections/shared/Sidebar';
import { ProfessorDashboard } from '@/sections/professor/ProfessorDashboard';
import { AIContentGenerator } from '@/sections/professor/AIContentGenerator';
import { AIQuizGenerator } from '@/sections/professor/AIQuizGenerator';
import { StudentDashboard } from '@/sections/student/StudentDashboard';
import { AITutor } from '@/sections/student/AITutor';
import './App.css';

// =============================================================================
// PLACEHOLDER COMPONENTS (for views not yet implemented)
// =============================================================================

function PlaceholderView({ title, description }: { title: string; description: string }) {
  return (
    <div className="h-full flex items-center justify-center p-8">
      <div className="text-center max-w-md">
        <div className="w-20 h-20 bg-indigo-100 rounded-full flex items-center justify-center mx-auto mb-6">
          <span className="text-3xl">🚧</span>
        </div>
        <h2 className="text-2xl font-bold text-slate-800 mb-2">{title}</h2>
        <p className="text-slate-500">{description}</p>
      </div>
    </div>
  );
}

// Professor views
function CoursesView() {
  return (
    <PlaceholderView 
      title="Course Management" 
      description="Create and manage your courses. This feature is coming soon!" 
    />
  );
}

function AnalyticsView() {
  return (
    <PlaceholderView 
      title="Student Analytics" 
      description="View detailed analytics about student performance and progress." 
    />
  );
}

function GradebookView() {
  return (
    <PlaceholderView 
      title="Gradebook" 
      description="Manage grades and provide feedback to students." 
    />
  );
}

// Student views
function AssignmentsView() {
  return (
    <PlaceholderView 
      title="Assignments" 
      description="View and submit your assignments." 
    />
  );
}

function ProgressView() {
  return (
    <PlaceholderView 
      title="My Progress" 
      description="Track your learning progress across all courses." 
    />
  );
}

function StudyMaterialsView() {
  return (
    <PlaceholderView 
      title="Study Materials" 
      description="Access all your course materials in one place." 
    />
  );
}

// Shared views
function SettingsView() {
  return (
    <PlaceholderView 
      title="Settings" 
      description="Manage your account settings and preferences." 
    />
  );
}

// =============================================================================
// MAIN LAYOUT COMPONENT
// =============================================================================

function MainLayout() {
  const { isProfessor, isStudent } = useAuth();
  const [currentView, setCurrentView] = useState('dashboard');
  const [isSidebarCollapsed, setIsSidebarCollapsed] = useState(false);

  // Define available views based on role
  const views: Record<string, React.ReactNode> = {
    // Professor views
    ...(isProfessor && {
      dashboard: <ProfessorDashboard onViewChange={setCurrentView} />,
      courses: <CoursesView />,
      'ai-generator': <AIContentGenerator onViewChange={setCurrentView} />,
      'quiz-builder': <AIQuizGenerator onViewChange={setCurrentView} />,
      analytics: <AnalyticsView />,
      gradebook: <GradebookView />,
      'ai-tutor': <AITutor onViewChange={setCurrentView} />,
    }),
    // Student views
    ...(isStudent && {
      dashboard: <StudentDashboard onViewChange={setCurrentView} />,
      courses: <CoursesView />,
      'ai-tutor': <AITutor onViewChange={setCurrentView} />,
      assignments: <AssignmentsView />,
      progress: <ProgressView />,
      materials: <StudyMaterialsView />,
    }),
    // Shared views
    settings: <SettingsView />,
  };

  // Get current view component
  const CurrentViewComponent = views[currentView] || views['dashboard'];

  return (
    <div className="h-screen flex overflow-hidden bg-slate-50">
      {/* Sidebar Navigation */}
      <Sidebar
        currentView={currentView}
        onViewChange={setCurrentView}
        isCollapsed={isSidebarCollapsed}
        onToggleCollapse={() => setIsSidebarCollapsed(!isSidebarCollapsed)}
      />

      {/* Main Content Area */}
      <main className="flex-1 overflow-hidden">
        <div className="h-full overflow-auto">
          {CurrentViewComponent}
        </div>
      </main>
    </div>
  );
}

// =============================================================================
// AUTH WRAPPER COMPONENT
// =============================================================================

function AuthWrapper() {
  const { isAuthenticated, isLoading } = useAuth();

  // Show loading state
  if (isLoading) {
    return (
      <div className="h-screen flex items-center justify-center bg-slate-50">
        <div className="text-center">
          <div className="w-16 h-16 border-4 border-indigo-200 border-t-indigo-600 rounded-full animate-spin mx-auto mb-4" />
          <p className="text-slate-500">Loading...</p>
        </div>
      </div>
    );
  }

  // Show login screen if not authenticated
  if (!isAuthenticated) {
    return <LoginScreen />;
  }

  // Show main app if authenticated
  return <MainLayout />;
}

// =============================================================================
// ROOT APP COMPONENT
// =============================================================================

function App() {
  return (
    <AuthProvider>
      <AppProvider>
        <AuthWrapper />
        <Toaster position="top-right" />
      </AppProvider>
    </AuthProvider>
  );
}

export default App;
