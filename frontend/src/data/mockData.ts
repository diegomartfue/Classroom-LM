/**
 * ============================================================================
 * MOCK DATA - LearnAI Platform
 * ============================================================================
 * 
 * This file contains all mock data used to simulate the backend.
 * In a production app, these would be API calls to a server.
 * 
 * To modify data:
 * 1. Edit the objects in this file
 * 2. The changes will reflect immediately in the UI
 * 
 * To connect to a real backend:
 * 1. Replace the functions in this file with API calls
 * 2. Keep the same return types for easy migration
 * 
 * ============================================================================
 */

import type {
  User,
  Professor,
  Student,
  Course,
  CourseModule,
  Quiz,
  Question,
  QuizAttempt,
  Conversation,
  StudentProgress,
  Notification,
} from '@/types';

// =============================================================================
// USERS
// =============================================================================

export const mockUsers: User[] = [
  {
    id: 'prof-1',
    email: 'dr.chen@university.edu',
    name: 'Dr. Sarah Chen',
    role: 'professor',
    avatar: 'https://api.dicebear.com/7.x/avataaars/svg?seed=dr-chen',
    createdAt: new Date('2023-01-15'),
    lastLoginAt: new Date(),
  },
  {
    id: 'student-1',
    email: 'alex.johnson@student.edu',
    name: 'Alex Johnson',
    role: 'student',
    avatar: 'https://api.dicebear.com/7.x/avataaars/svg?seed=alex',
    createdAt: new Date('2023-09-01'),
    lastLoginAt: new Date(),
  },
  {
    id: 'student-2',
    email: 'maria.garcia@student.edu',
    name: 'Maria Garcia',
    role: 'student',
    avatar: 'https://api.dicebear.com/7.x/avataaars/svg?seed=maria',
    createdAt: new Date('2023-09-01'),
    lastLoginAt: new Date(),
  },
  {
    id: 'student-3',
    email: 'james.wilson@student.edu',
    name: 'James Wilson',
    role: 'student',
    avatar: 'https://api.dicebear.com/7.x/avataaars/svg?seed=james',
    createdAt: new Date('2023-09-01'),
    lastLoginAt: new Date(),
  },
];

export const mockProfessors: Professor[] = [
  {
    ...mockUsers[0],
    role: 'professor',
    department: 'Mechanical Engineering',
    title: 'Dr.',
    courses: ['course-1', 'course-2'],
  },
];

export const mockStudents: Student[] = [
  {
    ...mockUsers[1],
    role: 'student',
    studentId: 'ST2023001',
    major: 'Mechanical Engineering',
    enrollmentYear: 2023,
    enrolledCourses: ['course-1', 'course-2'],
    overallProgress: 78,
    streakDays: 5,
  },
  {
    ...mockUsers[2],
    role: 'student',
    studentId: 'ST2023002',
    major: 'Mechanical Engineering',
    enrollmentYear: 2023,
    enrolledCourses: ['course-1'],
    overallProgress: 92,
    streakDays: 12,
  },
  {
    ...mockUsers[3],
    role: 'student',
    studentId: 'ST2023003',
    major: 'Civil Engineering',
    enrollmentYear: 2023,
    enrolledCourses: ['course-2'],
    overallProgress: 65,
    streakDays: 3,
  },
];

// =============================================================================
// COURSES
// =============================================================================

export const mockCourses: Course[] = [
  {
    id: 'course-1',
    code: 'MECH-101',
    name: 'Introduction to Mechanical Engineering',
    description: 'Fundamental concepts in mechanical engineering including statics, dynamics, and thermodynamics.',
    professorId: 'prof-1',
    status: 'active',
    createdAt: new Date('2024-01-10'),
    updatedAt: new Date(),
    studentIds: ['student-1', 'student-2'],
    moduleIds: ['module-1', 'module-2', 'module-3'],
    coverImage: 'https://images.unsplash.com/photo-1581092921461-eab62e97a782?w=800&h=400&fit=crop',
  },
  {
    id: 'course-2',
    code: 'THERMO-201',
    name: 'Thermodynamics',
    description: 'Study of heat, work, energy, and their relationships in engineering systems.',
    professorId: 'prof-1',
    status: 'active',
    createdAt: new Date('2024-01-15'),
    updatedAt: new Date(),
    studentIds: ['student-1', 'student-3'],
    moduleIds: ['module-4', 'module-5'],
    coverImage: 'https://images.unsplash.com/photo-1507668077129-56e32842fceb?w=800&h=400&fit=crop',
  },
];

// =============================================================================
// COURSE MODULES
// =============================================================================

export const mockModules: CourseModule[] = [
  {
    id: 'module-1',
    courseId: 'course-1',
    title: 'Forces and Equilibrium',
    description: 'Understanding force vectors, equilibrium conditions, and free-body diagrams.',
    content: `
      <h2>Forces and Equilibrium</h2>
      <p>In mechanical engineering, understanding forces is fundamental. A <strong>force</strong> is a vector quantity that causes an object to accelerate.</p>
      
      <h3>Key Concepts</h3>
      <ul>
        <li>Force vectors and components</li>
        <li>Newton's First Law (Equilibrium)</li>
        <li>Free-body diagrams</li>
        <li>Support reactions</li>
      </ul>
      
      <h3>Equilibrium Equations</h3>
      <p>For a body in equilibrium:</p>
      <p>ΣFₓ = 0, ΣFᵧ = 0, ΣFᵤ = 0</p>
      <p>ΣM = 0 (sum of moments)</p>
      
      <h3>Example Problem</h3>
      <p>A 100 kg beam is supported at two points. Calculate the reactions...</p>
    `,
    order: 1,
    estimatedDuration: 45,
    isAIGenerated: false,
    createdAt: new Date('2024-01-12'),
    updatedAt: new Date(),
  },
  {
    id: 'module-2',
    courseId: 'course-1',
    title: 'Stress and Strain Analysis',
    description: 'Introduction to material deformation under load.',
    content: `
      <h2>Stress and Strain</h2>
      <p>When forces are applied to materials, they deform. Understanding this behavior is crucial for engineering design.</p>
      
      <h3>Normal Stress</h3>
      <p>σ = F/A</p>
      <p>Where σ is stress, F is force, and A is cross-sectional area.</p>
      
      <h3>Normal Strain</h3>
      <p>ε = ΔL/L₀</p>
      
      <h3>Hooke's Law</h3>
      <p>σ = E × ε</p>
      <p>E is the Young's Modulus, a material property.</p>
    `,
    order: 2,
    estimatedDuration: 60,
    isAIGenerated: true,
    aiMetadata: {
      generatedFor: 'class',
      difficultyLevel: 3,
      learningObjectives: ['Calculate normal stress', 'Understand stress-strain relationship', 'Apply Hooke\'s Law'],
    },
    createdAt: new Date('2024-01-20'),
    updatedAt: new Date(),
  },
  {
    id: 'module-3',
    courseId: 'course-1',
    title: 'Kinematics of Particles',
    description: 'Motion analysis without considering forces.',
    content: '<h2>Kinematics</h2><p>Study of motion...</p>',
    order: 3,
    estimatedDuration: 50,
    isAIGenerated: false,
    createdAt: new Date('2024-01-25'),
    updatedAt: new Date(),
  },
  {
    id: 'module-4',
    courseId: 'course-2',
    title: 'First Law of Thermodynamics',
    description: 'Energy conservation in thermodynamic systems.',
    content: `
      <h2>First Law of Thermodynamics</h2>
      <p>The First Law states that energy cannot be created or destroyed, only transferred or converted.</p>
      
      <h3>Mathematical Formulation</h3>
      <p>ΔU = Q - W</p>
      <p>Where:</p>
      <ul>
        <li>ΔU = change in internal energy</li>
        <li>Q = heat added to system</li>
        <li>W = work done by system</li>
      </ul>
      
      <h3>For a Closed System</h3>
      <p>Q - W = ΔE = ΔU + ΔKE + ΔPE</p>
    `,
    order: 1,
    estimatedDuration: 55,
    isAIGenerated: true,
    aiMetadata: {
      generatedFor: 'class',
      difficultyLevel: 4,
      learningObjectives: ['Apply First Law to closed systems', 'Calculate internal energy changes', 'Analyze thermodynamic processes'],
    },
    createdAt: new Date('2024-02-01'),
    updatedAt: new Date(),
  },
  {
    id: 'module-5',
    courseId: 'course-2',
    title: 'Heat Engines and Efficiency',
    description: 'Understanding thermal efficiency and the Carnot cycle.',
    content: '<h2>Heat Engines</h2><p>Thermal efficiency...</p>',
    order: 2,
    estimatedDuration: 65,
    isAIGenerated: true,
    aiMetadata: {
      generatedFor: 'student',
      targetStudentId: 'student-3',
      difficultyLevel: 3,
      learningObjectives: ['Calculate thermal efficiency', 'Understand Carnot cycle', 'Compare engine types'],
      personalizationReason: 'Student struggled with heat transfer concepts in previous quiz',
    },
    createdAt: new Date('2024-02-10'),
    updatedAt: new Date(),
  },
];

// =============================================================================
// QUIZZES
// =============================================================================

export const mockQuestions: Question[] = [
  // Quiz 1 Questions
  {
    id: 'q-1-1',
    type: 'multiple_choice',
    question: 'What is the condition for static equilibrium?',
    points: 5,
    options: [
      'ΣF = 0 only',
      'ΣF = 0 and ΣM = 0',
      'ΣM = 0 only',
      'ΣF = ma',
    ],
    correctOptionIndex: 1,
    explanation: 'For static equilibrium, both the sum of forces and sum of moments must equal zero.',
  },
  {
    id: 'q-1-2',
    type: 'equation_solving',
    question: 'A 500 N force acts at 30° to the horizontal. Calculate the horizontal component.',
    points: 10,
    correctAnswer: '433',
    explanation: 'Fₓ = F × cos(30°) = 500 × 0.866 = 433 N',
  },
  {
    id: 'q-1-3',
    type: 'fill_blank',
    question: 'Hooke\'s Law states that stress is _______ proportional to strain.',
    points: 5,
    correctAnswer: 'directly',
    explanation: 'Hooke\'s Law: σ = Eε, showing direct proportionality.',
  },
  // Quiz 2 Questions (AI Generated)
  {
    id: 'q-2-1',
    type: 'equation_solving',
    question: 'Calculate the thermal efficiency of a heat engine operating between reservoirs at 800K and 300K.',
    points: 15,
    correctAnswer: '62.5',
    explanation: 'η = 1 - Tₗ/Tₕ = 1 - 300/800 = 0.625 = 62.5%',
  },
  {
    id: 'q-2-2',
    type: 'multiple_choice',
    question: 'In the First Law of Thermodynamics, Q represents:',
    points: 5,
    options: [
      'Work done by the system',
      'Heat added to the system',
      'Change in internal energy',
      'Entropy change',
    ],
    correctOptionIndex: 1,
    explanation: 'Q represents heat transfer into the system.',
  },
];

export const mockQuizzes: Quiz[] = [
  {
    id: 'quiz-1',
    courseId: 'course-1',
    title: 'Forces and Equilibrium Quiz',
    description: 'Test your understanding of force vectors and equilibrium conditions.',
    questions: [mockQuestions[0], mockQuestions[1], mockQuestions[2]],
    timeLimit: 30,
    totalPoints: 20,
    isAIGenerated: false,
    createdAt: new Date('2024-01-20'),
    dueDate: new Date('2024-02-01'),
    status: 'published',
  },
  {
    id: 'quiz-2',
    courseId: 'course-2',
    title: 'Thermodynamics Fundamentals',
    description: 'Assessment on First Law and thermal efficiency.',
    questions: [mockQuestions[3], mockQuestions[4]],
    timeLimit: 45,
    totalPoints: 20,
    isAIGenerated: true,
    aiMetadata: {
      generatedFor: 'class',
      difficultyDistribution: { easy: 20, medium: 50, hard: 30 },
      topicFocus: ['First Law', 'Thermal Efficiency', 'Heat Engines'],
    },
    createdAt: new Date('2024-02-15'),
    dueDate: new Date('2024-03-01'),
    status: 'published',
  },
];

// =============================================================================
// QUIZ ATTEMPTS
// =============================================================================

export const mockQuizAttempts: QuizAttempt[] = [
  {
    id: 'attempt-1',
    quizId: 'quiz-1',
    studentId: 'student-1',
    startedAt: new Date('2024-01-25'),
    submittedAt: new Date('2024-01-25'),
    answers: [
      { questionId: 'q-1-1', answer: 1, isCorrect: true, pointsEarned: 5 },
      { questionId: 'q-1-2', answer: '430', isCorrect: false, pointsEarned: 0 },
      { questionId: 'q-1-3', answer: 'directly', isCorrect: true, pointsEarned: 5 },
    ],
    score: 10,
    maxScore: 20,
    status: 'graded',
    aiFeedback: {
      overallFeedback: 'Good understanding of equilibrium concepts. Practice vector component calculations.',
      strengths: ['Static equilibrium conditions', 'Hooke\'s Law application'],
      weaknesses: ['Trigonometric calculations', 'Precision in numerical answers'],
      suggestedTopics: ['Vector resolution', 'Significant figures'],
      personalizedRecommendations: 'Review trigonometric functions and practice more force component problems.',
    },
  },
  {
    id: 'attempt-2',
    quizId: 'quiz-1',
    studentId: 'student-2',
    startedAt: new Date('2024-01-26'),
    submittedAt: new Date('2024-01-26'),
    answers: [
      { questionId: 'q-1-1', answer: 1, isCorrect: true, pointsEarned: 5 },
      { questionId: 'q-1-2', answer: '433', isCorrect: true, pointsEarned: 10 },
      { questionId: 'q-1-3', answer: 'directly', isCorrect: true, pointsEarned: 5 },
    ],
    score: 20,
    maxScore: 20,
    status: 'graded',
    aiFeedback: {
      overallFeedback: 'Excellent work! Perfect score on all questions.',
      strengths: ['All topics mastered'],
      weaknesses: [],
      suggestedTopics: ['Advanced equilibrium problems'],
      personalizedRecommendations: 'Move on to more complex multi-body equilibrium problems.',
    },
  },
];

// =============================================================================
// CONVERSATIONS (AI Tutor)
// =============================================================================

export const mockConversations: Conversation[] = [
  {
    id: 'conv-1',
    userId: 'student-1',
    title: 'Force Components Help',
    messages: [
      {
        id: 'msg-1-1',
        conversationId: 'conv-1',
        sender: 'user',
        type: 'text',
        content: 'I\'m struggling with calculating force components. Can you explain?',
        timestamp: new Date('2024-01-22T10:00:00'),
      },
      {
        id: 'msg-1-2',
        conversationId: 'conv-1',
        sender: 'ai',
        type: 'text',
        content: 'I\'d be happy to help! When a force acts at an angle, we break it into horizontal (x) and vertical (y) components using trigonometry.\n\nFor a force F at angle θ:\n• Horizontal: Fₓ = F × cos(θ)\n• Vertical: Fᵧ = F × sin(θ)\n\nWould you like to work through an example problem?',
        timestamp: new Date('2024-01-22T10:00:05'),
      },
      {
        id: 'msg-1-3',
        conversationId: 'conv-1',
        sender: 'user',
        type: 'equation',
        content: 'Can you show me with F = 100N at 45°?',
        latexContent: 'F = 100N, \\theta = 45°',
        timestamp: new Date('2024-01-22T10:01:00'),
      },
      {
        id: 'msg-1-4',
        conversationId: 'conv-1',
        sender: 'ai',
        type: 'equation',
        content: 'Sure! For F = 100N at 45°:\n\nFₓ = 100 × cos(45°) = 100 × 0.707 = 70.7 N\nFᵧ = 100 × sin(45°) = 100 × 0.707 = 70.7 N\n\nAt 45°, both components are equal!',
        latexContent: 'F_x = 100 \\times \\cos(45°) = 70.7N\\nF_y = 100 \\times \\sin(45°) = 70.7N',
        timestamp: new Date('2024-01-22T10:01:10'),
      },
    ],
    createdAt: new Date('2024-01-22'),
    updatedAt: new Date('2024-01-22'),
    contextCourseId: 'course-1',
  },
];

// =============================================================================
// STUDENT PROGRESS
// =============================================================================

export const mockProgressRecords: StudentProgress[] = [
  {
    studentId: 'student-1',
    courseId: 'course-1',
    overallMastery: 75,
    topicMastery: [
      { topic: 'Force Vectors', masteryLevel: 85, attempts: 5, lastAssessedAt: new Date() },
      { topic: 'Equilibrium', masteryLevel: 90, attempts: 4, lastAssessedAt: new Date() },
      { topic: 'Stress-Strain', masteryLevel: 60, attempts: 3, lastAssessedAt: new Date() },
      { topic: 'Free Body Diagrams', masteryLevel: 70, attempts: 4, lastAssessedAt: new Date() },
    ],
    quizScores: [
      { quizId: 'quiz-1', quizTitle: 'Forces and Equilibrium Quiz', score: 10, maxScore: 20, completedAt: new Date() },
    ],
    studyTimeMinutes: 420,
    lastActivityAt: new Date(),
    streakDays: 5,
  },
  {
    studentId: 'student-2',
    courseId: 'course-1',
    overallMastery: 92,
    topicMastery: [
      { topic: 'Force Vectors', masteryLevel: 95, attempts: 4, lastAssessedAt: new Date() },
      { topic: 'Equilibrium', masteryLevel: 95, attempts: 3, lastAssessedAt: new Date() },
      { topic: 'Stress-Strain', masteryLevel: 88, attempts: 3, lastAssessedAt: new Date() },
      { topic: 'Free Body Diagrams', masteryLevel: 92, attempts: 3, lastAssessedAt: new Date() },
    ],
    quizScores: [
      { quizId: 'quiz-1', quizTitle: 'Forces and Equilibrium Quiz', score: 20, maxScore: 20, completedAt: new Date() },
    ],
    studyTimeMinutes: 380,
    lastActivityAt: new Date(),
    streakDays: 12,
  },
  {
    studentId: 'student-3',
    courseId: 'course-2',
    overallMastery: 65,
    topicMastery: [
      { topic: 'First Law', masteryLevel: 70, attempts: 4, lastAssessedAt: new Date() },
      { topic: 'Heat Engines', masteryLevel: 55, attempts: 3, lastAssessedAt: new Date() },
      { topic: 'Thermal Efficiency', masteryLevel: 60, attempts: 3, lastAssessedAt: new Date() },
      { topic: 'Carnot Cycle', masteryLevel: 50, attempts: 2, lastAssessedAt: new Date() },
    ],
    quizScores: [],
    studyTimeMinutes: 280,
    lastActivityAt: new Date(),
    streakDays: 3,
  },
];

// =============================================================================
// NOTIFICATIONS
// =============================================================================

export const mockNotifications: Notification[] = [
  {
    id: 'notif-1',
    userId: 'student-1',
    type: 'grade',
    title: 'Quiz Graded',
    message: 'Your Forces and Equilibrium Quiz has been graded. Score: 10/20',
    isRead: false,
    createdAt: new Date(),
    actionUrl: '/student/quiz/quiz-1',
  },
  {
    id: 'notif-2',
    userId: 'student-1',
    type: 'ai_suggestion',
    title: 'AI Study Recommendation',
    message: 'Based on your quiz performance, try the personalized module on Vector Components.',
    isRead: false,
    createdAt: new Date(),
    actionUrl: '/student/modules/module-personalized-1',
  },
  {
    id: 'notif-3',
    userId: 'prof-1',
    type: 'assignment',
    title: 'Quiz Submitted',
    message: 'Alex Johnson submitted the Thermodynamics Fundamentals quiz.',
    isRead: true,
    createdAt: new Date(),
    actionUrl: '/professor/quiz/quiz-2/attempts',
  },
];

// =============================================================================
// HELPER FUNCTIONS
// =============================================================================

export function getUserById(id: string): User | undefined {
  return mockUsers.find(u => u.id === id);
}

export function getStudentById(id: string): Student | undefined {
  return mockStudents.find(s => s.id === id);
}

export function getProfessorById(id: string): Professor | undefined {
  return mockProfessors.find(p => p.id === id);
}

export function getCourseById(id: string): Course | undefined {
  return mockCourses.find(c => c.id === id);
}

export function getModulesByCourse(courseId: string): CourseModule[] {
  return mockModules.filter(m => m.courseId === courseId).sort((a, b) => a.order - b.order);
}

export function getQuizzesByCourse(courseId: string): Quiz[] {
  return mockQuizzes.filter(q => q.courseId === courseId);
}

export function getProgressByStudent(studentId: string): StudentProgress[] {
  return mockProgressRecords.filter(p => p.studentId === studentId);
}

export function getNotificationsByUser(userId: string): Notification[] {
  return mockNotifications.filter(n => n.userId === userId).sort((a, b) => b.createdAt.getTime() - a.createdAt.getTime());
}

export function getConversationsByUser(userId: string): Conversation[] {
  return mockConversations.filter(c => c.userId === userId);
}
