/**
 * ============================================================================
 * LOGIN SCREEN - LearnAI Platform
 * ============================================================================
 * 
 * The authentication entry point for the application.
 * Supports both Professor and Student login with role selection.
 * 
 * FEATURES:
 * - Role toggle (Professor/Student)
 * - Form validation
 * - Loading states
 * - Demo account hints
 * - Smooth animations
 * 
 * ============================================================================
 */

import React, { useState } from 'react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Sparkles, GraduationCap, Users, Loader2, BookOpen } from 'lucide-react';
import { useAuth } from '@/contexts';
import type { UserRole } from '@/types';

export function LoginScreen() {
  const { login, isLoading } = useAuth();
  const [role, setRole] = useState<UserRole>('student');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);

    if (!email.trim()) {
      setError('Please enter your email');
      return;
    }

    try {
      await login(email, password, role);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Login failed');
    }
  };

  const fillDemoCredentials = (demoRole: UserRole) => {
    setRole(demoRole);
    setEmail(`${demoRole}@demo.com`);
    setPassword('demo');
    setError(null);
  };

  return (
    <div className="min-h-screen flex">
      {/* Left Side - Branding */}
      <div className="hidden lg:flex lg:w-1/2 bg-gradient-to-br from-indigo-600 via-indigo-700 to-teal-600 relative overflow-hidden">
        {/* Animated background elements */}
        <div className="absolute inset-0 overflow-hidden">
          <div className="absolute -top-40 -left-40 w-80 h-80 bg-white/10 rounded-full blur-3xl animate-pulse" />
          <div className="absolute top-1/2 -right-20 w-60 h-60 bg-teal-400/20 rounded-full blur-3xl animate-pulse delay-700" />
          <div className="absolute -bottom-20 left-1/3 w-72 h-72 bg-indigo-400/20 rounded-full blur-3xl animate-pulse delay-1000" />
        </div>

        <div className="relative z-10 flex flex-col justify-center px-16 text-white">
          <div className="flex items-center gap-3 mb-8">
            <div className="w-14 h-14 bg-white/20 rounded-2xl flex items-center justify-center backdrop-blur-sm">
              <Sparkles className="w-8 h-8 text-white" />
            </div>
            <span className="text-3xl font-bold">LearnAI</span>
          </div>

          <h1 className="text-5xl font-bold mb-6 leading-tight">
            AI-Powered Learning,<br />
            <span className="text-teal-300">Personalized</span> for Every Student
          </h1>

          <p className="text-xl text-indigo-100 mb-12 max-w-md leading-relaxed">
            Experience the future of education with intelligent tutoring, 
            personalized content, and real-time progress analytics.
          </p>

          <div className="space-y-4">
            <div className="flex items-center gap-4 bg-white/10 rounded-xl p-4 backdrop-blur-sm">
              <div className="w-10 h-10 bg-teal-500/30 rounded-lg flex items-center justify-center">
                <BookOpen className="w-5 h-5 text-teal-300" />
              </div>
              <div>
                <p className="font-semibold">Smart Learning Modules</p>
                <p className="text-sm text-indigo-200">AI-generated content tailored to each student</p>
              </div>
            </div>

            <div className="flex items-center gap-4 bg-white/10 rounded-xl p-4 backdrop-blur-sm">
              <div className="w-10 h-10 bg-pink-500/30 rounded-lg flex items-center justify-center">
                <GraduationCap className="w-5 h-5 text-pink-300" />
              </div>
              <div>
                <p className="font-semibold">Intelligent Assessments</p>
                <p className="text-sm text-indigo-200">Adaptive quizzes that evolve with student progress</p>
              </div>
            </div>

            <div className="flex items-center gap-4 bg-white/10 rounded-xl p-4 backdrop-blur-sm">
              <div className="w-10 h-10 bg-orange-500/30 rounded-lg flex items-center justify-center">
                <Users className="w-5 h-5 text-orange-300" />
              </div>
              <div>
                <p className="font-semibold">24/7 AI Tutor</p>
                <p className="text-sm text-indigo-200">Get help with equations and diagrams anytime</p>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Right Side - Login Form */}
      <div className="flex-1 flex items-center justify-center bg-gradient-to-br from-slate-50 to-indigo-50/50 p-8">
        <div className="w-full max-w-md">
          {/* Mobile Logo */}
          <div className="lg:hidden flex items-center justify-center gap-3 mb-8">
            <div className="w-12 h-12 bg-indigo-600 rounded-xl flex items-center justify-center">
              <Sparkles className="w-6 h-6 text-white" />
            </div>
            <span className="text-2xl font-bold text-slate-800">LearnAI</span>
          </div>

          <Card className="shadow-2xl border-0 bg-white/80 backdrop-blur-sm">
            <CardHeader className="space-y-1">
              <CardTitle className="text-2xl font-bold text-center">Welcome Back</CardTitle>
              <CardDescription className="text-center">
                Sign in to access your learning dashboard
              </CardDescription>
            </CardHeader>

            <CardContent className="space-y-6">
              {/* Role Selection */}
              <Tabs value={role} onValueChange={(v) => setRole(v as UserRole)} className="w-full">
                <TabsList className="grid w-full grid-cols-2">
                  <TabsTrigger value="student" className="flex items-center gap-2">
                    <GraduationCap className="w-4 h-4" />
                    Student
                  </TabsTrigger>
                  <TabsTrigger value="professor" className="flex items-center gap-2">
                    <Users className="w-4 h-4" />
                    Professor
                  </TabsTrigger>
                </TabsList>
              </Tabs>

              {/* Error Message */}
              {error && (
                <Alert variant="destructive" className="animate-in fade-in slide-in-from-top-2">
                  <AlertDescription>{error}</AlertDescription>
                </Alert>
              )}

              {/* Login Form */}
              <form onSubmit={handleSubmit} className="space-y-4">
                <div className="space-y-2">
                  <Label htmlFor="email">Email</Label>
                  <Input
                    id="email"
                    type="email"
                    placeholder={`${role}@university.edu`}
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    className="h-11"
                    disabled={isLoading}
                  />
                </div>

                <div className="space-y-2">
                  <Label htmlFor="password">Password</Label>
                  <Input
                    id="password"
                    type="password"
                    placeholder="Enter your password"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    className="h-11"
                    disabled={isLoading}
                  />
                </div>

                <Button
                  type="submit"
                  className="w-full h-11 bg-indigo-600 hover:bg-indigo-700 text-white font-semibold"
                  disabled={isLoading}
                >
                  {isLoading ? (
                    <>
                      <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                      Signing in...
                    </>
                  ) : (
                    'Sign In'
                  )}
                </Button>
              </form>

              {/* Demo Accounts */}
              <div className="pt-4 border-t border-slate-200">
                <p className="text-sm text-slate-500 text-center mb-3">Quick demo login:</p>
                <div className="flex gap-2">
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    className="flex-1"
                    onClick={() => fillDemoCredentials('student')}
                    disabled={isLoading}
                  >
                    <GraduationCap className="w-4 h-4 mr-2" />
                    Student Demo
                  </Button>
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    className="flex-1"
                    onClick={() => fillDemoCredentials('professor')}
                    disabled={isLoading}
                  >
                    <Users className="w-4 h-4 mr-2" />
                    Professor Demo
                  </Button>
                </div>
              </div>
            </CardContent>
          </Card>

          <p className="text-center text-sm text-slate-500 mt-6">
            By signing in, you agree to our Terms of Service and Privacy Policy
          </p>
        </div>
      </div>
    </div>
  );
}
