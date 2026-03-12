/**
 * ============================================================================
 * STUDENT DASHBOARD - LearnAI Platform
 * ============================================================================
 * 
 * The main dashboard view for students showing their progress,
>Continuing from where the response was cut off:

 enrolled courses, and quick access to the AI tutor.
 * 
 * FEATURES:
 * - Progress overview with animated charts
 * - Active courses with progress bars
 * - AI Tutor quick access
 * - Upcoming deadlines
 * 
 * ============================================================================
 */

import { useEffect, useState } from 'react';
import { cn } from '@/lib/utils';
import { useAuth, useApp } from '@/contexts';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import {
  Bot,
  BookOpen,
  Calendar,
  Clock,
  Flame,
  TrendingUp,
  Target,
  ChevronRight,
  Sparkles,
  FileQuestion,
  Zap,
} from 'lucide-react';
import { mockCourses, mockStudents } from '@/data/mockData';

// =============================================================================
// ANIMATED PROGRESS RING
// =============================================================================

function ProgressRing({ 
  percentage, 
  size = 80, 
  strokeWidth = 8, 
  color = 'indigo',
  label 
}: { 
  percentage: number; 
  size?: number; 
  strokeWidth?: number;
  color?: string;
  label?: string;
}) {
  const [animatedPercentage, setAnimatedPercentage] = useState(0);
  const radius = (size - strokeWidth) / 2;
  const circumference = radius * 2 * Math.PI;
  const offset = circumference - (animatedPercentage / 100) * circumference;

  useEffect(() => {
    const timer = setTimeout(() => setAnimatedPercentage(percentage), 100);
    return () => clearTimeout(timer);
  }, [percentage]);

  const colorClasses: Record<string, string> = {
    indigo: 'stroke-indigo-500',
    teal: 'stroke-teal-500',
    coral: 'stroke-orange-500',
    pink: 'stroke-pink-500',
  };

  return (
    <div className="relative" style={{ width: size, height: size }}>
      <svg width={size} height={size} className="transform -rotate-90">
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke="currentColor"
          strokeWidth={strokeWidth}
          className="text-slate-100"
        />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke="currentColor"
          strokeWidth={strokeWidth}
          strokeLinecap="round"
          className={cn('transition-all duration-1000 ease-out', colorClasses[color] || colorClasses.indigo)}
          strokeDasharray={circumference}
          strokeDashoffset={offset}
        />
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center">
        <span className="text-xl font-bold text-slate-800">{Math.round(animatedPercentage)}%</span>
        {label && <span className="text-xs text-slate-500">{label}</span>}
      </div>
    </div>
  );
}

// =============================================================================
// COURSE CARD COMPONENT
// =============================================================================

interface CourseCardProps {
  course: typeof mockCourses[0];
  progress: number;
  onClick: () => void;
  delay?: number;
}

function CourseCard({ course, progress, onClick, delay = 0 }: CourseCardProps) {
  const [isVisible, setIsVisible] = useState(false);

  useEffect(() => {
    const timer = setTimeout(() => setIsVisible(true), delay);
    return () => clearTimeout(timer);
  }, [delay]);

  return (
    <Card
      onClick={onClick}
      className={cn(
        'border-0 shadow-lg hover:shadow-xl transition-all duration-500 cursor-pointer overflow-hidden group',
        isVisible ? 'opacity-100 translate-y-0' : 'opacity-0 translate-y-4'
      )}
    >
      <div className="h-32 bg-gradient-to-br from-indigo-100 to-teal-100 relative overflow-hidden">
        {course.coverImage && (
          <img
            src={course.coverImage}
            alt={course.name}
            className="w-full h-full object-cover group-hover:scale-105 transition-transform duration-500"
          />
        )}
        <div className="absolute inset-0 bg-gradient-to-t from-black/60 to-transparent" />
        <div className="absolute bottom-3 left-4 right-4">
          <Badge className="bg-white/90 text-slate-800 text-xs mb-2">
            {course.code}
          </Badge>
          <h3 className="font-semibold text-white text-sm line-clamp-2">{course.name}</h3>
        </div>
      </div>
      <CardContent className="p-4">
        <div className="space-y-2">
          <div className="flex items-center justify-between text-sm">
            <span className="text-slate-500">Progress</span>
            <span className="font-medium text-slate-700">{progress}%</span>
          </div>
          <div className="h-2 bg-slate-100 rounded-full overflow-hidden">
            <div
              className={cn(
                'h-full rounded-full transition-all duration-1000 ease-out',
                progress >= 80 ? 'bg-green-500' : progress >= 50 ? 'bg-yellow-500' : 'bg-indigo-500'
              )}
              style={{ width: `${progress}%` }}
            />
          </div>
          <p className="text-xs text-slate-400">
            {course.moduleIds.length} modules • {Math.round(progress * course.moduleIds.length / 100)} completed
          </p>
        </div>
      </CardContent>
    </Card>
  );
}

// =============================================================================
// MAIN DASHBOARD COMPONENT
// =============================================================================

interface StudentDashboardProps {
  onViewChange: (view: string) => void;
}

export function StudentDashboard({ onViewChange }: StudentDashboardProps) {
  const { user } = useAuth();
  const { getStudentProgress } = useApp();
  
  const student = mockStudents.find(s => s.id === user?.id);
  // Progress records available for future use
  void getStudentProgress;
  
  // Get enrolled courses
  const enrolledCourses = mockCourses.filter(c => student?.enrolledCourses.includes(c.id));
  
  // Mock progress for demo
  const courseProgress: Record<string, number> = {
    'course-1': 75,
    'course-2': 45,
  };

  // Upcoming deadlines (mock)
  const upcomingDeadlines = [
    { id: 1, title: 'Forces and Equilibrium Quiz', course: 'MECH-101', date: 'Tomorrow', type: 'quiz' },
    { id: 2, title: 'Thermodynamics Assignment', course: 'THERMO-201', date: 'In 3 days', type: 'assignment' },
    { id: 3, title: 'Stress Analysis Module', course: 'MECH-101', date: 'In 5 days', type: 'module' },
  ];

  // Get greeting based on time
  const getGreeting = () => {
    const hour = new Date().getHours();
    if (hour < 12) return 'Good morning';
    if (hour < 18) return 'Good afternoon';
    return 'Good evening';
  };

  return (
    <div className="p-8 space-y-8 animate-in fade-in duration-500">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold text-slate-800">
            {getGreeting()}, {user?.name?.split(' ')[0]}!
          </h1>
          <p className="text-slate-500 mt-1">
            Ready to continue your learning journey?
          </p>
        </div>
        <div className="flex items-center gap-4">
          <div className="flex items-center gap-2 px-4 py-2 bg-orange-50 rounded-xl border border-orange-200">
            <Flame className="w-5 h-5 text-orange-500" />
            <div>
              <p className="text-xs text-orange-600">Study Streak</p>
              <p className="font-bold text-orange-700">{student?.streakDays || 0} days</p>
            </div>
          </div>
        </div>
      </div>

      {/* Progress Overview */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        <Card className="border-0 shadow-lg">
          <CardContent className="p-6">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm text-slate-500 mb-1">Overall Progress</p>
                <p className="text-3xl font-bold text-slate-800">{student?.overallProgress || 0}%</p>
                <p className="text-sm text-slate-400 mt-1">Across all courses</p>
              </div>
              <ProgressRing percentage={student?.overallProgress || 0} color="indigo" />
            </div>
          </CardContent>
        </Card>

        <Card className="border-0 shadow-lg">
          <CardContent className="p-6">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm text-slate-500 mb-1">Average Score</p>
                <p className="text-3xl font-bold text-slate-800">82%</p>
                <p className="text-sm text-green-500 mt-1 flex items-center gap-1">
                  <TrendingUp className="w-4 h-4" />
                  +5% this month
                </p>
              </div>
              <ProgressRing percentage={82} color="teal" />
            </div>
          </CardContent>
        </Card>

        <Card className="border-0 shadow-lg">
          <CardContent className="p-6">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm text-slate-500 mb-1">Study Time</p>
                <p className="text-3xl font-bold text-slate-800">24h</p>
                <p className="text-sm text-slate-400 mt-1">This week</p>
              </div>
              <div className="w-20 h-20 bg-indigo-100 rounded-full flex items-center justify-center">
                <Clock className="w-10 h-10 text-indigo-500" />
              </div>
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Main Content Grid */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
        {/* Left Column - Courses & AI Tutor */}
        <div className="lg:col-span-2 space-y-8">
          {/* AI Tutor Card */}
          <Card 
            className="border-0 shadow-xl bg-gradient-to-br from-indigo-600 to-purple-600 text-white cursor-pointer hover:shadow-2xl hover:scale-[1.02] transition-all duration-300"
            onClick={() => onViewChange('ai-tutor')}
          >
            <CardContent className="p-8">
              <div className="flex items-center gap-6">
                <div className="w-20 h-20 bg-white/20 rounded-2xl flex items-center justify-center backdrop-blur-sm">
                  <Bot className="w-10 h-10 text-white" />
                </div>
                <div className="flex-1">
                  <div className="flex items-center gap-2 mb-2">
                    <Sparkles className="w-5 h-5 text-yellow-300" />
                    <span className="text-sm font-medium text-indigo-200">AI-Powered Learning</span>
                  </div>
                  <h2 className="text-2xl font-bold mb-2">Ask Your AI Tutor</h2>
                  <p className="text-indigo-100">
                    Get help with equations, diagrams, or any concept. Available 24/7.
                  </p>
                </div>
                <Button variant="secondary" className="bg-white text-indigo-600 hover:bg-indigo-50">
                  Start Chat
                  <ChevronRight className="w-4 h-4 ml-1" />
                </Button>
              </div>
            </CardContent>
          </Card>

          {/* Active Courses */}
          <div>
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-xl font-semibold text-slate-800 flex items-center gap-2">
                <BookOpen className="w-5 h-5 text-indigo-500" />
                My Courses
              </h2>
              <Button variant="ghost" className="text-indigo-600" onClick={() => onViewChange('courses')}>
                View All
                <ChevronRight className="w-4 h-4 ml-1" />
              </Button>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {enrolledCourses.map((course, index) => (
                <CourseCard
                  key={course.id}
                  course={course}
                  progress={courseProgress[course.id] || 0}
                  onClick={() => onViewChange('courses')}
                  delay={200 + index * 100}
                />
              ))}
            </div>
          </div>

          {/* Recommended for You */}
          <div>
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-xl font-semibold text-slate-800 flex items-center gap-2">
                <Target className="w-5 h-5 text-teal-500" />
                Recommended for You
              </h2>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <Card className="border-0 shadow-md hover:shadow-lg transition-all cursor-pointer border-l-4 border-l-teal-500">
                <CardContent className="p-4">
                  <div className="flex items-start gap-3">
                    <div className="w-10 h-10 bg-teal-100 rounded-lg flex items-center justify-center">
                      <BookOpen className="w-5 h-5 text-teal-600" />
                    </div>
                    <div className="flex-1">
                      <div className="flex items-center gap-2 mb-1">
                        <Badge variant="secondary" className="text-xs bg-teal-100 text-teal-700">AI Generated</Badge>
                      </div>
                      <h3 className="font-medium text-slate-800">Force Vector Practice</h3>
                      <p className="text-sm text-slate-500">Personalized based on your quiz results</p>
                    </div>
                  </div>
                </CardContent>
              </Card>

              <Card className="border-0 shadow-md hover:shadow-lg transition-all cursor-pointer border-l-4 border-l-indigo-500">
                <CardContent className="p-4">
                  <div className="flex items-start gap-3">
                    <div className="w-10 h-10 bg-indigo-100 rounded-lg flex items-center justify-center">
                      <FileQuestion className="w-5 h-5 text-indigo-600" />
                    </div>
                    <div className="flex-1">
                      <div className="flex items-center gap-2 mb-1">
                        <Badge variant="secondary" className="text-xs bg-indigo-100 text-indigo-700">Quiz</Badge>
                      </div>
                      <h3 className="font-medium text-slate-800">Thermodynamics Review</h3>
                      <p className="text-sm text-slate-500">Test your understanding before the exam</p>
                    </div>
                  </div>
                </CardContent>
              </Card>
            </div>
          </div>
        </div>

        {/* Right Column - Deadlines & Quick Actions */}
        <div className="space-y-6">
          {/* Upcoming Deadlines */}
          <Card className="border-0 shadow-lg">
            <CardHeader>
              <CardTitle className="text-lg flex items-center gap-2">
                <Calendar className="w-5 h-5 text-indigo-500" />
                Upcoming Deadlines
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              {upcomingDeadlines.map((deadline) => (
                <div
                  key={deadline.id}
                  className="flex items-start gap-3 p-3 rounded-xl hover:bg-slate-50 transition-colors cursor-pointer"
                >
                  <div className={cn(
                    'w-10 h-10 rounded-lg flex items-center justify-center flex-shrink-0',
                    deadline.type === 'quiz' ? 'bg-red-100' : 'bg-amber-100'
                  )}>
                    {deadline.type === 'quiz' ? (
                      <FileQuestion className="w-5 h-5 text-red-500" />
                    ) : (
                      <BookOpen className="w-5 h-5 text-amber-500" />
                    )}
                  </div>
                  <div className="flex-1 min-w-0">
                    <p className="font-medium text-slate-800 text-sm">{deadline.title}</p>
                    <p className="text-xs text-slate-500">{deadline.course}</p>
                    <Badge 
                      variant="secondary" 
                      className={cn(
                        'text-xs mt-1',
                        deadline.date === 'Tomorrow' ? 'bg-red-100 text-red-700' : 'bg-slate-100'
                      )}
                    >
                      {deadline.date}
                    </Badge>
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
              <Button 
                variant="outline" 
                className="w-full justify-start gap-2" 
                onClick={() => onViewChange('ai-tutor')}
              >
                <Bot className="w-4 h-4 text-indigo-500" />
                Ask AI Tutor
              </Button>
              <Button 
                variant="outline" 
                className="w-full justify-start gap-2" 
                onClick={() => onViewChange('assignments')}
              >
                <FileQuestion className="w-4 h-4 text-teal-500" />
                View Assignments
              </Button>
              <Button 
                variant="outline" 
                className="w-full justify-start gap-2" 
                onClick={() => onViewChange('progress')}
              >
                <TrendingUp className="w-4 h-4 text-pink-500" />
                Check Progress
              </Button>
            </CardContent>
          </Card>

          {/* AI Study Tip */}
          <Card className="border-0 shadow-lg bg-gradient-to-br from-teal-500 to-cyan-600 text-white">
            <CardContent className="p-6">
              <div className="flex items-center gap-2 mb-3">
                <Zap className="w-5 h-5" />
                <span className="font-semibold">AI Study Tip</span>
              </div>
              <p className="text-sm text-teal-100 leading-relaxed">
                Based on your progress, spend 15 minutes reviewing force vectors today. 
                You're close to mastering this topic!
              </p>
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}
