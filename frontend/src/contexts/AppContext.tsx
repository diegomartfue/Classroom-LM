/**
 * ============================================================================
 * APP CONTEXT - LearnAI Platform
 * ============================================================================
 * 
 * This context manages global application state including courses, modules,
 * quizzes, and AI-generated content. It provides CRUD operations and
 * AI simulation functionality.
 * 
 * ARCHITECTURE:
 * - Uses React Context API for global state
 * - Works with mock data (easily replaceable with API calls)
 * - Provides AI simulation functions
 * 
 * USAGE:
 * ```tsx
 * const { courses, modules, generateAIModule, generateAIQuiz } = useApp();
 * ```
 * 
 * ============================================================================
 */

import React, { createContext, useContext, useState, useCallback, useMemo } from 'react';
import type { 
  Course, 
  CourseModule, 
  Quiz, 
  Question, 
  StudentProgress,
  ModuleGenerationParams,
  QuizGenerationParams,
  Notification,
  Conversation,
  ChatMessage,
} from '@/types';
import { 
  mockCourses, 
  mockModules, 
  mockQuizzes, 
  mockProgressRecords,
  mockNotifications,
  mockConversations,
} from '@/data/mockData';
import { useAuth } from './AuthContext';

// =============================================================================
// TYPES
// =============================================================================

interface AppContextType {
  // Data
  courses: Course[];
  modules: CourseModule[];
  quizzes: Quiz[];
  progressRecords: StudentProgress[];
  notifications: Notification[];
  conversations: Conversation[];
  
  // Loading states
  isGenerating: boolean;
  
  // Course operations
  getCourse: (id: string) => Course | undefined;
  getCourseModules: (courseId: string) => CourseModule[];
  getCourseQuizzes: (courseId: string) => Quiz[];
  createCourse: (course: Omit<Course, 'id' | 'createdAt' | 'updatedAt'>) => Course;
  updateCourse: (id: string, updates: Partial<Course>) => void;
  
  // Module operations
  getModule: (id: string) => CourseModule | undefined;
  createModule: (module: Omit<CourseModule, 'id' | 'createdAt' | 'updatedAt'>) => CourseModule;
  updateModule: (id: string, updates: Partial<CourseModule>) => void;
  
  // Quiz operations
  getQuiz: (id: string) => Quiz | undefined;
  createQuiz: (quiz: Omit<Quiz, 'id' | 'createdAt'>) => Quiz;
  updateQuiz: (id: string, updates: Partial<Quiz>) => void;
  publishQuiz: (id: string) => void;
  
  // AI Generation
  generateAIModule: (courseId: string, params: ModuleGenerationParams, targetStudentId?: string) => Promise<CourseModule>;
  generateAIQuiz: (courseId: string, params: QuizGenerationParams, targetStudentId?: string) => Promise<Quiz>;
  
  // Progress & Analytics
  getStudentProgress: (studentId: string) => StudentProgress[];
  getCourseProgress: (courseId: string) => StudentProgress[];
  
  // Notifications
  markNotificationRead: (id: string) => void;
  
  // AI Tutor
  sendMessageToAI: (conversationId: string, message: string, displayMessage?: string) => Promise<ChatMessage>;
  createConversation: (title: string, courseId?: string) => Conversation;
}

// =============================================================================
// CONTEXT CREATION
// =============================================================================

const AppContext = createContext<AppContextType | undefined>(undefined);

// =============================================================================
// AI SIMULATION FUNCTIONS
// =============================================================================

/**
 * Simulates AI module generation
 * In production, this would call an AI API (OpenAI, Claude, etc.)
 */
async function simulateAIModuleGeneration(
  courseId: string,
  params: ModuleGenerationParams,
  targetStudentId?: string
): Promise<CourseModule> {
  // Simulate API delay
  await new Promise(resolve => setTimeout(resolve, 2000));
  
  const id = `module-ai-${Date.now()}`;
  
  // Generate content based on topic
  const content = generateModuleContent(params.topic, params.difficultyLevel, params.includeEquations);
  
  return {
    id,
    courseId,
    title: params.topic,
    description: `AI-generated module on ${params.topic} at difficulty level ${params.difficultyLevel}/5`,
    content,
    order: 999, // Will be updated when added to course
    estimatedDuration: params.estimatedDuration,
    isAIGenerated: true,
    aiMetadata: {
      generatedFor: targetStudentId ? 'student' : 'class',
      targetStudentId,
      difficultyLevel: params.difficultyLevel,
      learningObjectives: params.learningObjectives,
      personalizationReason: targetStudentId ? 'Based on student performance analysis' : undefined,
    },
    createdAt: new Date(),
    updatedAt: new Date(),
  };
}

/**
 * Generates sample module content
 */
function generateModuleContent(topic: string, difficulty: number, includeEquations: boolean): string {
  const equations = includeEquations ? `
    <h3>Key Equations</h3>
    <div class="equation-block">
      <p>F = ma (Newton's Second Law)</p>
      <p>ΣF = 0 (Equilibrium Condition)</p>
    </div>
  ` : '';
  
  return `
    <h2>${topic}</h2>
    <p>This AI-generated module covers ${topic} at a ${difficulty === 1 ? 'beginner' : difficulty === 5 ? 'advanced' : 'intermediate'} level.</p>
    
    <h3>Learning Objectives</h3>
    <ul>
      <li>Understand core concepts of ${topic}</li>
      <li>Apply principles to solve problems</li>
      <li>Analyze real-world applications</li>
    </ul>
    
    <h3>Introduction</h3>
    <p>${topic} is a fundamental concept in engineering. Understanding this topic is essential for advancing in your studies.</p>
    
    ${equations}
    
    <h3>Applications</h3>
    <p>These concepts are applied in various engineering fields including mechanical design, structural analysis, and system optimization.</p>
    
    <h3>Practice Problems</h3>
    <ol>
      <li>Calculate the reaction forces in a simple beam.</li>
      <li>Determine the stress distribution in a loaded column.</li>
      <li>Analyze the equilibrium of a truss structure.</li>
    </ol>
  `;
}

/**
 * Simulates AI quiz generation
 */
async function simulateAIQuizGeneration(
  courseId: string,
  params: QuizGenerationParams,
  targetStudentId?: string
): Promise<Quiz> {
  await new Promise(resolve => setTimeout(resolve, 2500));
  
  const id = `quiz-ai-${Date.now()}`;
  const questions: Question[] = [];
  
  // Generate questions based on parameters
  for (let i = 0; i < params.questionCount; i++) {
    const type = params.questionTypes[i % params.questionTypes.length];
    questions.push(generateQuestion(i + 1, type, params.topicFocus[i % params.topicFocus.length]));
  }
  
  return {
    id,
    courseId,
    title: params.title,
    description: `AI-generated quiz focusing on ${params.topicFocus.join(', ')}`,
    questions,
    timeLimit: params.timeLimit,
    totalPoints: questions.reduce((sum, q) => sum + q.points, 0),
    isAIGenerated: true,
    aiMetadata: {
      generatedFor: targetStudentId ? 'student' : 'class',
      targetStudentId,
      difficultyDistribution: params.difficultyDistribution,
      topicFocus: params.topicFocus,
    },
    createdAt: new Date(),
    dueDate: new Date(Date.now() + 7 * 24 * 60 * 60 * 1000), // 7 days from now
    status: 'draft',
  };
}

/**
 * Generates a sample question
 */
function generateQuestion(number: number, type: string, topic: string): Question {
  const basePoints = type === 'multiple_choice' ? 5 : type === 'equation_solving' ? 15 : 10;
  
  switch (type) {
    case 'multiple_choice':
      return {
        id: `q-ai-${number}`,
        type: 'multiple_choice',
        question: `Sample multiple choice question about ${topic}?`,
        points: basePoints,
        options: ['Option A', 'Option B', 'Option C', 'Option D'],
        correctOptionIndex: 0,
        explanation: `This tests your understanding of ${topic}.`,
      };
    case 'equation_solving':
      return {
        id: `q-ai-${number}`,
        type: 'equation_solving',
        question: `Solve for x in the following equation related to ${topic}: 2x + 5 = 15`,
        points: basePoints,
        correctAnswer: '5',
        explanation: 'Subtract 5 from both sides: 2x = 10, then divide by 2: x = 5',
      };
    case 'fill_blank':
      return {
        id: `q-ai-${number}`,
        type: 'fill_blank',
        question: `The study of ${topic} involves understanding _______ principles.`,
        points: basePoints,
        correctAnswer: 'fundamental',
        explanation: `${topic} is built on fundamental principles.`,
      };
    default:
      return {
        id: `q-ai-${number}`,
        type: 'essay',
        question: `Explain the concept of ${topic} and its applications.`,
        points: basePoints,
        rubric: 'Clear explanation: 5pts, Examples: 3pts, Applications: 2pts',
      };
  }
}

/**
 * Simulates AI tutor response
 */
async function simulateAITutorResponse(
  message: string, 
  model: string = "qwen",
  conversationHistory: { role: string; content: string }[] = []
): Promise<string> {
  try {
    const response = await fetch("http://127.0.0.1:8000/chat", {
      method: "POST",
      headers: {
        "Content-Type": "application/json"},
      body: JSON.stringify({
        message,
        model,
        role: "student",
        conversation_history: conversationHistory,
      }),
    });

    if (!response.ok) {
      throw new Error("Backend request failed");
    }

    const data = await response.json();
    
    // If SymPy verified the answer, append a note
    if (data.sympy_verified && data.sympy_result) {
      return data.response + `\n\n✓ *Answer verified by SymPy: ${
        Array.isArray(data.sympy_result.solution) 
          ? data.sympy_result.solution.join(", ") 
          : data.sympy_result.solution
      }*`;
    }

    return data.response;

  } catch (error) {
    return "Sorry, I couldn't connect to the AI backend. Make sure the server is running.";
  }
}

// =============================================================================
// PROVIDER COMPONENT
// =============================================================================

export function AppProvider({ children }: { children: React.ReactNode }) {
  const { user } = useAuth();
  
  // State
  const [courses, setCourses] = useState<Course[]>(mockCourses);
  const [modules, setModules] = useState<CourseModule[]>(mockModules);
  const [quizzes, setQuizzes] = useState<Quiz[]>(mockQuizzes);
  const [progressRecords] = useState<StudentProgress[]>(mockProgressRecords);
  const [notifications, setNotifications] = useState<Notification[]>(mockNotifications);
  const [conversations, setConversations] = useState<Conversation[]>(mockConversations);
  const [isGenerating, setIsGenerating] = useState(false);

  // =============================================================================
  // COURSE OPERATIONS
  // =============================================================================

  const getCourse = useCallback((id: string) => {
    return courses.find(c => c.id === id);
  }, [courses]);

  const getCourseModules = useCallback((courseId: string) => {
    return modules.filter(m => m.courseId === courseId).sort((a, b) => a.order - b.order);
  }, [modules]);

  const getCourseQuizzes = useCallback((courseId: string) => {
    return quizzes.filter(q => q.courseId === courseId);
  }, [quizzes]);

  const createCourse = useCallback((courseData: Omit<Course, 'id' | 'createdAt' | 'updatedAt'>) => {
    const newCourse: Course = {
      ...courseData,
      id: `course-${Date.now()}`,
      createdAt: new Date(),
      updatedAt: new Date(),
    };
    setCourses(prev => [...prev, newCourse]);
    return newCourse;
  }, []);

  const updateCourse = useCallback((id: string, updates: Partial<Course>) => {
    setCourses(prev => prev.map(c => 
      c.id === id ? { ...c, ...updates, updatedAt: new Date() } : c
    ));
  }, []);

  // =============================================================================
  // MODULE OPERATIONS
  // =============================================================================

  const getModule = useCallback((id: string) => {
    return modules.find(m => m.id === id);
  }, [modules]);

  const createModule = useCallback((moduleData: Omit<CourseModule, 'id' | 'createdAt' | 'updatedAt'>) => {
    const newModule: CourseModule = {
      ...moduleData,
      id: `module-${Date.now()}`,
      createdAt: new Date(),
      updatedAt: new Date(),
    };
    setModules(prev => [...prev, newModule]);
    return newModule;
  }, []);

  const updateModule = useCallback((id: string, updates: Partial<CourseModule>) => {
    setModules(prev => prev.map(m => 
      m.id === id ? { ...m, ...updates, updatedAt: new Date() } : m
    ));
  }, []);

  // =============================================================================
  // QUIZ OPERATIONS
  // =============================================================================

  const getQuiz = useCallback((id: string) => {
    return quizzes.find(q => q.id === id);
  }, [quizzes]);

  const createQuiz = useCallback((quizData: Omit<Quiz, 'id' | 'createdAt'>) => {
    const newQuiz: Quiz = {
      ...quizData,
      id: `quiz-${Date.now()}`,
      createdAt: new Date(),
    };
    setQuizzes(prev => [...prev, newQuiz]);
    return newQuiz;
  }, []);

  const updateQuiz = useCallback((id: string, updates: Partial<Quiz>) => {
    setQuizzes(prev => prev.map(q => 
      q.id === id ? { ...q, ...updates } : q
    ));
  }, []);

  const publishQuiz = useCallback((id: string) => {
    setQuizzes(prev => prev.map(q => 
      q.id === id ? { ...q, status: 'published' } : q
    ));
  }, []);

  // =============================================================================
  // AI GENERATION
  // =============================================================================

  const generateAIModule = useCallback(async (
    courseId: string, 
    params: ModuleGenerationParams,
    targetStudentId?: string
  ) => {
    setIsGenerating(true);
    try {
      const module = await simulateAIModuleGeneration(courseId, params, targetStudentId);
      setModules(prev => [...prev, module]);
      
      // Update course's module list
      setCourses(prev => prev.map(c => 
        c.id === courseId 
          ? { ...c, moduleIds: [...c.moduleIds, module.id], updatedAt: new Date() }
          : c
      ));
      
      return module;
    } finally {
      setIsGenerating(false);
    }
  }, []);

  const generateAIQuiz = useCallback(async (
    courseId: string,
    params: QuizGenerationParams,
    targetStudentId?: string
  ) => {
    setIsGenerating(true);
    try {
      const quiz = await simulateAIQuizGeneration(courseId, params, targetStudentId);
      setQuizzes(prev => [...prev, quiz]);
      return quiz;
    } finally {
      setIsGenerating(false);
    }
  }, []);

  // =============================================================================
  // PROGRESS & ANALYTICS
  // =============================================================================

  const getStudentProgress = useCallback((studentId: string) => {
    return progressRecords.filter(p => p.studentId === studentId);
  }, [progressRecords]);

  const getCourseProgress = useCallback((courseId: string) => {
    return progressRecords.filter(p => {
      const course = courses.find(c => c.id === courseId);
      return course?.studentIds.includes(p.studentId);
    });
  }, [progressRecords, courses]);

  // =============================================================================
  // NOTIFICATIONS
  // =============================================================================

  const markNotificationRead = useCallback((id: string) => {
    setNotifications(prev => prev.map(n => 
      n.id === id ? { ...n, isRead: true } : n
    ));
  }, []);

  // =============================================================================
  // AI TUTOR
  // =============================================================================

  const sendMessageToAI = useCallback(async (
    conversationId: string,
    message: string,
    displayMessage?: string
  ) => {
    const userMessage: ChatMessage = {
      id: `msg-${Date.now()}-user`,
      conversationId,
      sender: 'user',
      type: 'text',
      content: displayMessage ?? message,
      timestamp: new Date(),
    };

    // Add user message immediately
    setConversations(prev => prev.map(conv => {
      if (conv.id === conversationId) {
        return {
          ...conv,
          messages: [...conv.messages, userMessage],
          updatedAt: new Date(),
        };
      }
      return conv;
    }));


    // Build history from existing messages (before the new user message)
  const conversation = conversations.find(c => c.id === conversationId);
  const history = (conversation?.messages ?? []).map(m => ({
    role: m.sender === 'user' ? 'user' : 'assistant',
    content: m.content,
  }));
    
  const response = await simulateAITutorResponse(message, "qwen", history);

  const aiMessage: ChatMessage = {
    id: `msg-${Date.now()}-ai`,
    conversationId,
    sender: 'ai',
    type: 'text',
    content: response,
    timestamp: new Date(),
  };

  setConversations(prev => prev.map(conv => {
    if (conv.id === conversationId) {
      return { ...conv, messages: [...conv.messages, aiMessage], updatedAt: new Date() };
    }
    return conv;
  }));

  return aiMessage;
}, [conversations]);  

  const createConversation = useCallback((title: string, courseId?: string) => {
    const newConversation: Conversation = {
      id: `conv-${Date.now()}`,
      userId: user?.id || '',
      title,
      messages: [],
      createdAt: new Date(),
      updatedAt: new Date(),
      contextCourseId: courseId,
    };
    setConversations(prev => [...prev, newConversation]);
    return newConversation;
  }, [user]);

  // =============================================================================
  // VALUE MEMOIZATION
  // =============================================================================

  const value = useMemo<AppContextType>(() => ({
    courses,
    modules,
    quizzes,
    progressRecords,
    notifications,
    conversations,
    isGenerating,
    getCourse,
    getCourseModules,
    getCourseQuizzes,
    createCourse,
    updateCourse,
    getModule,
    createModule,
    updateModule,
    getQuiz,
    createQuiz,
    updateQuiz,
    publishQuiz,
    generateAIModule,
    generateAIQuiz,
    getStudentProgress,
    getCourseProgress,
    markNotificationRead,
    sendMessageToAI,
    createConversation,
  }), [
    courses, modules, quizzes, progressRecords, notifications, conversations, isGenerating,
    getCourse, getCourseModules, getCourseQuizzes, createCourse, updateCourse,
    getModule, createModule, updateModule,
    getQuiz, createQuiz, updateQuiz, publishQuiz,
    generateAIModule, generateAIQuiz,
    getStudentProgress, getCourseProgress,
    markNotificationRead,
    sendMessageToAI, createConversation,
  ]);

  return (
    <AppContext.Provider value={value}>
      {children}
    </AppContext.Provider>
  );
}

// =============================================================================
// HOOK
// =============================================================================

export function useApp() {
  const context = useContext(AppContext);
  if (context === undefined) {
    throw new Error('useApp must be used within an AppProvider');
  }
  return context;
}
