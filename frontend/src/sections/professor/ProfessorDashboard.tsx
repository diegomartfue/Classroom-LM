/**
 * ============================================================================
 * PROFESSOR DASHBOARD - LearnAI Platform
 * ============================================================================
 * 
 * The main dashboard view for professors showing key metrics,
 * AI tools, and recent activity.
 * 
 * FEATURES:
 * - Key statistics cards with animations
 * - Quick-access AI tool cards
 * - Recent activity feed
 * - Course overview
 * 
 * ============================================================================
 */

import { useEffect, useState } from 'react';
import { cn } from '@/lib/utils';
import { useAuth, useApp } from '@/contexts';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import {
  Sparkles,
  BookOpen,
  Users,
  FileQuestion,
  Clock,
  ChevronRight,
  Plus,
  MessageSquare,
  GraduationCap,
  BarChart3,
  Zap,
} from 'lucide-react';

// =============================================================================
// ANIMATED COUNTER COMPONENT
// =============================================================================

function AnimatedCounter({ value, duration = 1500 }: { value: number; duration?: number }) {
  const [displayValue, setDisplayValue] = useState(0);

  useEffect(() => {
    let startTime: number;
    let animationFrame: number;

    const animate = (timestamp: number) => {
      if (!startTime) startTime = timestamp;
      const progress = Math.min((timestamp - startTime) / duration, 1);
      
      // Ease out cubic
      const easeOut = 1 - Math.pow(1 - progress, 3);
      setDisplayValue(Math.floor(easeOut * value));

      if (progress < 1) {
        animationFrame = requestAnimationFrame(animate);
      }
    };

    animationFrame = requestAnimationFrame(animate);
    return () => cancelAnimationFrame(animationFrame);
  }, [value, duration]);

  return <span>{displayValue}</span>;
}

// =============================================================================
// STAT CARD COMPONENT
// =============================================================================

interface StatCardProps {
  title: string;
  value: number;
  subtitle: string;
  icon: React.ElementType;
  color: 'indigo' | 'teal' | 'coral' | 'pink';
  delay?: number;
}

function StatCard({ title, value, subtitle, icon: Icon, color, delay = 0 }: StatCardProps) {
  const [isVisible, setIsVisible] = useState(false);

  useEffect(() => {
    const timer = setTimeout(() => setIsVisible(true), delay);
    return () => clearTimeout(timer);
  }, [delay]);

  const colorClasses = {
    indigo: 'from-indigo-500 to-indigo-600',
    teal: 'from-teal-500 to-teal-600',
    coral: 'from-orange-500 to-orange-600',
    pink: 'from-pink-500 to-pink-600',
  };

  return (
    <Card
      className={cn(
        'border-0 shadow-lg hover:shadow-xl transition-all duration-500 hover:-translate-y-1',
        isVisible ? 'opacity-100 translate-y-0' : 'opacity-0 translate-y-4'
      )}
    >
      <CardContent className="p-6">
        <div className="flex items-start justify-between">
          <div>
            <p className="text-sm font-medium text-slate-500 mb-1">{title}</p>
            <p className="text-3xl font-bold text-slate-800">
              <AnimatedCounter value={value} />
            </p>
            <p className="text-sm text-slate-400 mt-1">{subtitle}</p>
          </div>
          <div className={cn('w-12 h-12 rounded-xl bg-gradient-to-br flex items-center justify-center', colorClasses[color])}>
            <Icon className="w-6 h-6 text-white" />
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

// =============================================================================
// AI TOOL CARD COMPONENT
// =============================================================================

interface AIToolCardProps {
  title: string;
  description: string;
  icon: React.ElementType;
  onClick: () => void;
  color: string;
  delay?: number;
}

function AIToolCard({ title, description, icon: Icon, onClick, color, delay = 0 }: AIToolCardProps) {
  const [isVisible, setIsVisible] = useState(false);

  useEffect(() => {
    const timer = setTimeout(() => setIsVisible(true), delay);
    return () => clearTimeout(timer);
  }, [delay]);

  return (
    <button
      onClick={onClick}
      className={cn(
        'w-full text-left p-6 rounded-2xl bg-white border-2 border-transparent hover:border-indigo-200 transition-all duration-300 group',
        'shadow-md hover:shadow-xl hover:-translate-y-1',
        isVisible ? 'opacity-100 translate-y-0' : 'opacity-0 translate-y-4'
      )}
    >
      <div className="flex items-start gap-4">
        <div
          className={cn(
            'w-14 h-14 rounded-xl flex items-center justify-center flex-shrink-0 transition-transform duration-300 group-hover:scale-110',
            color
          )}
        >
          <Icon className="w-7 h-7 text-white" />
        </div>
        <div className="flex-1">
          <div className="flex items-center gap-2 mb-1">
            <h3 className="font-semibold text-slate-800">{title}</h3>
            <Badge variant="secondary" className="bg-indigo-100 text-indigo-700 text-xs">
              <Sparkles className="w-3 h-3 mr-1" />
              AI
            </Badge>
          </div>
          <p className="text-sm text-slate-500 leading-relaxed">{description}</p>
        </div>
        <ChevronRight className="w-5 h-5 text-slate-300 group-hover:text-indigo-500 group-hover:translate-x-1 transition-all" />
      </div>
    </button>
  );
}

// =============================================================================
// MAIN DASHBOARD COMPONENT
// =============================================================================

interface ProfessorDashboardProps {
  onViewChange: (view: string) => void;
}

export function ProfessorDashboard({ onViewChange }: ProfessorDashboardProps) {
  const { user } = useAuth();
  const { courses, modules } = useApp();

  // Calculate stats
  const activeCourses = courses.filter(c => c.status === 'active').length;
  const totalStudents = courses.reduce((sum, c) => sum + c.studentIds.length, 0);
  const aiModules = modules.filter(m => m.isAIGenerated).length;
  const pendingGrades = 12; // Mock value

  // Recent activity (mock data)
  const recentActivity = [
    { id: 1, type: 'quiz', message: 'Alex Johnson submitted Thermodynamics Quiz', time: '5 min ago', icon: FileQuestion },
    { id: 2, type: 'ai', message: 'AI generated new module for James Wilson', time: '1 hour ago', icon: Sparkles },
    { id: 3, type: 'course', message: 'New student enrolled in MECH-101', time: '2 hours ago', icon: Users },
    { id: 4, type: 'message', message: 'Maria Garcia asked a question', time: '3 hours ago', icon: MessageSquare },
  ];

  return (
    <div className="p-8 space-y-8 animate-in fade-in duration-500">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold text-slate-800">
            Welcome back, {user?.name?.split(' ')[0]}!
          </h1>
          <p className="text-slate-500 mt-1">
            Here's what's happening in your courses today.
          </p>
        </div>
        <div className="flex gap-3">
          <Button variant="outline" className="gap-2">
            <Clock className="w-4 h-4" />
            View Schedule
          </Button>
          <Button className="gap-2 bg-indigo-600 hover:bg-indigo-700">
            <Plus className="w-4 h-4" />
            Create Course
          </Button>
        </div>
      </div>

      {/* Stats Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
        <StatCard
          title="Active Courses"
          value={activeCourses}
          subtitle="2 with upcoming deadlines"
          icon={BookOpen}
          color="indigo"
          delay={100}
        />
        <StatCard
          title="Total Students"
          value={totalStudents}
          subtitle="+3 this week"
          icon={Users}
          color="teal"
          delay={200}
        />
        <StatCard
          title="AI Modules Created"
          value={aiModules}
          subtitle="Personalized content"
          icon={Sparkles}
          color="coral"
          delay={300}
        />
        <StatCard
          title="Pending Grades"
          value={pendingGrades}
          subtitle="From 3 quizzes"
          icon={GraduationCap}
          color="pink"
          delay={400}
        />
      </div>

      {/* Main Content Grid */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
        {/* AI Tools Section */}
        <div className="lg:col-span-2 space-y-6">
          <div className="flex items-center justify-between">
            <h2 className="text-xl font-semibold text-slate-800 flex items-center gap-2">
              <Zap className="w-5 h-5 text-amber-500" />
              AI Teaching Tools
            </h2>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <AIToolCard
              title="Generate Learning Module"
              description="Create personalized or class-wide learning content with AI. Supports equations and diagrams."
              icon={BookOpen}
              color="bg-gradient-to-br from-indigo-500 to-indigo-600"
              onClick={() => onViewChange('ai-generator')}
              delay={500}
            />
            <AIToolCard
              title="Create AI Quiz"
              description="Generate adaptive assessments with multiple question types including equation solving."
              icon={FileQuestion}
              color="bg-gradient-to-br from-teal-500 to-teal-600"
              onClick={() => onViewChange('quiz-builder')}
              delay={600}
            />
            <AIToolCard
              title="Review Student Progress"
              description="View AI-analyzed performance data and personalized recommendations."
              icon={BarChart3}
              color="bg-gradient-to-br from-coral-500 to-orange-600"
              onClick={() => onViewChange('analytics')}
              delay={700}
            />
            <AIToolCard
              title="AI Tutor Assistant"
              description="Help students with questions, equations, and diagram analysis 24/7."
              icon={MessageSquare}
              color="bg-gradient-to-br from-pink-500 to-pink-600"
              onClick={() => onViewChange('ai-tutor')}
              delay={800}
            />
          </div>

          {/* Active Courses Preview */}
          <div className="pt-4">
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-xl font-semibold text-slate-800">Active Courses</h2>
              <Button variant="ghost" className="text-indigo-600" onClick={() => onViewChange('courses')}>
                View All
                <ChevronRight className="w-4 h-4 ml-1" />
              </Button>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {courses.filter(c => c.status === 'active').map((course, index) => (
                <Card
                  key={course.id}
                  className="border-0 shadow-md hover:shadow-lg transition-all duration-300 hover:-translate-y-1 cursor-pointer group"
                  style={{ animationDelay: `${900 + index * 100}ms` }}
                  onClick={() => onViewChange('courses')}
                >
                  <div className="h-32 bg-gradient-to-br from-indigo-100 to-teal-100 rounded-t-lg relative overflow-hidden">
                    {course.coverImage && (
                      <img
                        src={course.coverImage}
                        alt={course.name}
                        className="w-full h-full object-cover group-hover:scale-105 transition-transform duration-500"
                      />
                    )}
                    <div className="absolute inset-0 bg-gradient-to-t from-black/50 to-transparent" />
                    <Badge className="absolute top-3 left-3 bg-white/90 text-slate-800">
                      {course.code}
                    </Badge>
                  </div>
                  <CardContent className="p-4">
                    <h3 className="font-semibold text-slate-800 mb-1">{course.name}</h3>
                    <div className="flex items-center justify-between text-sm text-slate-500">
                      <span className="flex items-center gap-1">
                        <Users className="w-4 h-4" />
                        {course.studentIds.length} students
                      </span>
                      <span className="flex items-center gap-1">
                        <BookOpen className="w-4 h-4" />
                        {course.moduleIds.length} modules
                      </span>
                    </div>
                  </CardContent>
                </Card>
              ))}
            </div>
          </div>
        </div>

        {/* Right Sidebar - Activity & Quick Actions */}
        <div className="space-y-6">
          {/* Recent Activity */}
          <Card className="border-0 shadow-lg">
            <CardHeader>
              <CardTitle className="text-lg">Recent Activity</CardTitle>
              <CardDescription>Latest updates from your courses</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              {recentActivity.map((activity, index) => (
                <div
                  key={activity.id}
                  className="flex items-start gap-3 p-3 rounded-xl hover:bg-slate-50 transition-colors"
                  style={{ animationDelay: `${1000 + index * 100}ms` }}
                >
                  <div className="w-9 h-9 rounded-lg bg-indigo-100 flex items-center justify-center flex-shrink-0">
                    <activity.icon className="w-4 h-4 text-indigo-600" />
                  </div>
                  <div className="flex-1 min-w-0">
                    <p className="text-sm text-slate-700 leading-snug">{activity.message}</p>
                    <p className="text-xs text-slate-400 mt-1">{activity.time}</p>
                  </div>
                </div>
              ))}
            </CardContent>
          </Card>

          {/* Quick Actions */}
          <Card className="border-0 shadow-lg">
            <CardHeader>
              <CardTitle className="text-lg">Quick Actions</CardTitle>
            </CardHeader>
            <CardContent className="space-y-2">
              <Button variant="outline" className="w-full justify-start gap-2" onClick={() => onViewChange('ai-generator')}>
                <Sparkles className="w-4 h-4 text-indigo-500" />
                Generate AI Module
              </Button>
              <Button variant="outline" className="w-full justify-start gap-2" onClick={() => onViewChange('quiz-builder')}>
                <FileQuestion className="w-4 h-4 text-teal-500" />
                Create New Quiz
              </Button>
              <Button variant="outline" className="w-full justify-start gap-2">
                <MessageSquare className="w-4 h-4 text-pink-500" />
                Send Announcement
              </Button>
            </CardContent>
          </Card>

          {/* AI Insights */}
          <Card className="border-0 shadow-lg bg-gradient-to-br from-indigo-500 to-purple-600 text-white">
            <CardContent className="p-6">
              <div className="flex items-center gap-2 mb-3">
                <Sparkles className="w-5 h-5" />
                <span className="font-semibold">AI Insight</span>
              </div>
              <p className="text-sm text-indigo-100 leading-relaxed">
                3 students in MECH-101 are struggling with force vectors. 
                Consider generating a personalized practice module.
              </p>
              <Button
                variant="secondary"
                size="sm"
                className="mt-4 bg-white/20 text-white hover:bg-white/30 border-0"
                onClick={() => onViewChange('ai-generator')}
              >
                Generate Module
              </Button>
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}
