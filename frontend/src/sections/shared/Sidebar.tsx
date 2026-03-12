/**
 * ============================================================================
 * SIDEBAR NAVIGATION - LearnAI Platform
 * ============================================================================
 * 
 * Main navigation sidebar that adapts based on user role.
 * Shows different menu items for Professors vs Students.
 * 
 * FEATURES:
 * - Role-based navigation items
 * - Active state highlighting
 * - User profile card at bottom
 * - Collapsible on mobile
 * 
 * ============================================================================
 */

import { cn } from '@/lib/utils';
import { useAuth } from '@/contexts';
import { Button } from '@/components/ui/button';
import { Avatar, AvatarFallback, AvatarImage } from '@/components/ui/avatar';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Separator } from '@/components/ui/separator';
import {
  LayoutDashboard,
  BookOpen,
  Sparkles,
  FileQuestion,
  BarChart3,
  GraduationCap,
  Settings,
  LogOut,
  Bot,
  ClipboardList,
  ChevronLeft,
} from 'lucide-react';
import type { ElementType } from 'react';

// =============================================================================
// NAVIGATION ITEMS
// =============================================================================

interface NavItem {
  id: string;
  label: string;
  icon: ElementType;
  view: string;
}

const PROFESSOR_NAV_ITEMS: NavItem[] = [
  { id: 'dashboard', label: 'Dashboard', icon: LayoutDashboard, view: 'dashboard' },
  { id: 'courses', label: 'My Courses', icon: BookOpen, view: 'courses' },
  { id: 'ai-generator', label: 'AI Content Generator', icon: Sparkles, view: 'ai-generator' },
  { id: 'quiz-builder', label: 'Quiz Builder', icon: FileQuestion, view: 'quiz-builder' },
  { id: 'analytics', label: 'Student Analytics', icon: BarChart3, view: 'analytics' },
  { id: 'gradebook', label: 'Gradebook', icon: GraduationCap, view: 'gradebook' },
  { id: 'ai-tutor', label: 'AI Tutor', icon: Bot, view: 'ai-tutor' },
];

const STUDENT_NAV_ITEMS: NavItem[] = [
  { id: 'dashboard', label: 'Dashboard', icon: LayoutDashboard, view: 'dashboard' },
  { id: 'courses', label: 'My Courses', icon: BookOpen, view: 'courses' },
  { id: 'ai-tutor', label: 'AI Tutor', icon: Bot, view: 'ai-tutor' },
  { id: 'assignments', label: 'Assignments', icon: ClipboardList, view: 'assignments' },
  { id: 'progress', label: 'My Progress', icon: BarChart3, view: 'progress' },
  { id: 'study-materials', label: 'Study Materials', icon: BookOpen, view: 'materials' },
];

const BOTTOM_NAV_ITEMS: NavItem[] = [
  { id: 'settings', label: 'Settings', icon: Settings, view: 'settings' },
];

// =============================================================================
// COMPONENT
// =============================================================================

interface SidebarProps {
  currentView: string;
  onViewChange: (view: string) => void;
  isCollapsed: boolean;
  onToggleCollapse: () => void;
}

export function Sidebar({ currentView, onViewChange, isCollapsed, onToggleCollapse }: SidebarProps) {
  const { user, logout, isProfessor } = useAuth();

  const navItems = isProfessor ? PROFESSOR_NAV_ITEMS : STUDENT_NAV_ITEMS;

  const handleNavClick = (view: string) => {
    onViewChange(view);
  };

  const handleLogout = () => {
    logout();
  };

  return (
    <div
      className={cn(
        'h-screen bg-slate-800 flex flex-col transition-all duration-300 ease-in-out',
        isCollapsed ? 'w-20' : 'w-64'
      )}
    >
      {/* Logo Area */}
      <div className="h-16 flex items-center justify-between px-4 border-b border-slate-700">
        {!isCollapsed && (
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 bg-indigo-500 rounded-xl flex items-center justify-center">
              <Sparkles className="w-5 h-5 text-white" />
            </div>
            <span className="text-xl font-bold text-white">LearnAI</span>
          </div>
        )}
        {isCollapsed && (
          <div className="w-10 h-10 bg-indigo-500 rounded-xl flex items-center justify-center mx-auto">
            <Sparkles className="w-5 h-5 text-white" />
          </div>
        )}
        {!isCollapsed && (
          <Button
            variant="ghost"
            size="icon"
            className="text-slate-400 hover:text-white hover:bg-slate-700"
            onClick={onToggleCollapse}
          >
            <ChevronLeft className="w-5 h-5" />
          </Button>
        )}
      </div>

      {/* Navigation */}
      <ScrollArea className="flex-1 py-4">
        <nav className="space-y-1 px-3">
          {navItems.map((item) => {
            const isActive = currentView === item.view;
            const Icon = item.icon;

            return (
              <button
                key={item.id}
                onClick={() => handleNavClick(item.view)}
                className={cn(
                  'w-full flex items-center gap-3 px-3 py-3 rounded-xl transition-all duration-200 group relative',
                  isActive
                    ? 'bg-indigo-600 text-white'
                    : 'text-slate-400 hover:bg-slate-700/50 hover:text-white',
                  isCollapsed && 'justify-center px-2'
                )}
              >
                <Icon className={cn('w-5 h-5 flex-shrink-0', isActive && 'text-white')} />
                
                {!isCollapsed && (
                  <span className="font-medium text-sm">{item.label}</span>
                )}

                {/* Active indicator */}
                {isActive && !isCollapsed && (
                  <div className="absolute left-0 top-1/2 -translate-y-1/2 w-1 h-8 bg-teal-400 rounded-r-full" />
                )}

                {/* Tooltip for collapsed state */}
                {isCollapsed && (
                  <div className="absolute left-full ml-2 px-3 py-2 bg-slate-900 text-white text-sm rounded-lg opacity-0 invisible group-hover:opacity-100 group-hover:visible transition-all whitespace-nowrap z-50">
                    {item.label}
                  </div>
                )}
              </button>
            );
          })}
        </nav>
      </ScrollArea>

      {/* Bottom Section */}
      <div className="p-3 border-t border-slate-700 space-y-1">
        {/* Settings */}
        {BOTTOM_NAV_ITEMS.map((item) => {
          const Icon = item.icon;
          return (
            <button
              key={item.id}
              onClick={() => handleNavClick(item.view)}
              className={cn(
                'w-full flex items-center gap-3 px-3 py-3 rounded-xl transition-all duration-200 group relative',
                currentView === item.view
                  ? 'bg-slate-700 text-white'
                  : 'text-slate-400 hover:bg-slate-700/50 hover:text-white',
                isCollapsed && 'justify-center px-2'
              )}
            >
              <Icon className="w-5 h-5 flex-shrink-0" />
              {!isCollapsed && <span className="font-medium text-sm">{item.label}</span>}
              
              {isCollapsed && (
                <div className="absolute left-full ml-2 px-3 py-2 bg-slate-900 text-white text-sm rounded-lg opacity-0 invisible group-hover:opacity-100 group-hover:visible transition-all whitespace-nowrap z-50">
                  {item.label}
                </div>
              )}
            </button>
          );
        })}

        <Separator className="my-2 bg-slate-700" />

        {/* User Profile */}
        <div
          className={cn(
            'flex items-center gap-3 p-3 rounded-xl bg-slate-700/50',
            isCollapsed && 'justify-center'
          )}
        >
          <Avatar className="w-9 h-9 border-2 border-indigo-500">
            <AvatarImage src={user?.avatar} />
            <AvatarFallback className="bg-indigo-600 text-white text-sm">
              {user?.name?.charAt(0) || 'U'}
            </AvatarFallback>
          </Avatar>
          
          {!isCollapsed && (
            <div className="flex-1 min-w-0">
              <p className="text-sm font-medium text-white truncate">{user?.name}</p>
              <p className="text-xs text-slate-400 capitalize">{user?.role}</p>
            </div>
          )}

          {!isCollapsed && (
            <Button
              variant="ghost"
              size="icon"
              className="text-slate-400 hover:text-white hover:bg-slate-600"
              onClick={handleLogout}
            >
              <LogOut className="w-4 h-4" />
            </Button>
          )}
        </div>

        {/* Collapsed logout button */}
        {isCollapsed && (
          <button
            onClick={handleLogout}
            className="w-full flex items-center justify-center p-3 rounded-xl text-slate-400 hover:bg-slate-700 hover:text-white transition-all group relative"
          >
            <LogOut className="w-5 h-5" />
            <div className="absolute left-full ml-2 px-3 py-2 bg-slate-900 text-white text-sm rounded-lg opacity-0 invisible group-hover:opacity-100 group-hover:visible transition-all whitespace-nowrap z-50">
              Logout
            </div>
          </button>
        )}
      </div>
    </div>
  );
}
