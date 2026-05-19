-- CreateTable
CREATE TABLE "users" (
    "id" TEXT NOT NULL,
    "deviceUid" TEXT NOT NULL,
    "displayName" TEXT NOT NULL,
    "platform" TEXT,
    "appVersion" TEXT,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "lastSeenAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "users_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "questions" (
    "id" TEXT NOT NULL,
    "userId" TEXT NOT NULL,
    "rawText" TEXT NOT NULL,
    "normalizedText" TEXT,
    "status" TEXT NOT NULL,
    "currentCardId" TEXT,
    "helpRequestId" TEXT,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "questions_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "top1_cards" (
    "id" TEXT NOT NULL,
    "questionId" TEXT NOT NULL,
    "userId" TEXT NOT NULL,
    "source" TEXT NOT NULL,
    "title" TEXT NOT NULL,
    "subtitle" TEXT NOT NULL,
    "reason" TEXT NOT NULL,
    "bullets" JSONB NOT NULL,
    "warning" TEXT,
    "imageAssetId" TEXT NOT NULL,
    "confidence" DOUBLE PRECISION,
    "status" TEXT NOT NULL,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "top1_cards_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "image_assets" (
    "id" TEXT NOT NULL,
    "sourceType" TEXT NOT NULL,
    "url" TEXT NOT NULL,
    "thumbnailUrl" TEXT,
    "sourceUrl" TEXT,
    "credit" TEXT,
    "isAiGenerated" BOOLEAN NOT NULL DEFAULT false,
    "verificationStatus" TEXT NOT NULL,
    "placeKey" TEXT,
    "itemKey" TEXT,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "image_assets_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "help_requests" (
    "id" TEXT NOT NULL,
    "questionId" TEXT NOT NULL,
    "ownerUserId" TEXT NOT NULL,
    "title" TEXT NOT NULL,
    "contextText" TEXT NOT NULL,
    "status" TEXT NOT NULL,
    "answerCount" INTEGER NOT NULL DEFAULT 0,
    "minAnswersRequired" INTEGER NOT NULL DEFAULT 3,
    "finalCardId" TEXT,
    "publishedAt" TIMESTAMP(3),
    "finalReadyAt" TIMESTAMP(3),
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "help_requests_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "help_answers" (
    "id" TEXT NOT NULL,
    "helpRequestId" TEXT NOT NULL,
    "answerUserId" TEXT NOT NULL,
    "rawText" TEXT NOT NULL,
    "normalizedText" TEXT,
    "status" TEXT NOT NULL,
    "rewardStatus" TEXT NOT NULL,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "help_answers_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "pipi_runs" (
    "id" TEXT NOT NULL,
    "runType" TEXT NOT NULL,
    "questionId" TEXT,
    "helpRequestId" TEXT,
    "modelProvider" TEXT NOT NULL,
    "modelName" TEXT NOT NULL,
    "inputJson" JSONB NOT NULL,
    "outputJson" JSONB,
    "status" TEXT NOT NULL,
    "errorMessage" TEXT,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "pipi_runs_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "light_events" (
    "id" TEXT NOT NULL,
    "userId" TEXT NOT NULL,
    "questionId" TEXT,
    "helpRequestId" TEXT,
    "cardId" TEXT,
    "type" TEXT NOT NULL,
    "title" TEXT NOT NULL,
    "body" TEXT NOT NULL,
    "litAt" TIMESTAMP(3) NOT NULL,
    "expiresAt" TIMESTAMP(3),
    "seenAt" TIMESTAMP(3),
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "light_events_pkey" PRIMARY KEY ("id")
);

-- CreateIndex
CREATE UNIQUE INDEX "users_deviceUid_key" ON "users"("deviceUid");

-- CreateIndex
CREATE INDEX "questions_userId_createdAt_idx" ON "questions"("userId", "createdAt");

-- CreateIndex
CREATE INDEX "questions_status_idx" ON "questions"("status");

-- CreateIndex
CREATE INDEX "top1_cards_questionId_idx" ON "top1_cards"("questionId");

-- CreateIndex
CREATE INDEX "top1_cards_userId_idx" ON "top1_cards"("userId");

-- CreateIndex
CREATE INDEX "top1_cards_imageAssetId_idx" ON "top1_cards"("imageAssetId");

-- CreateIndex
CREATE INDEX "image_assets_verificationStatus_isAiGenerated_idx" ON "image_assets"("verificationStatus", "isAiGenerated");

-- CreateIndex
CREATE INDEX "image_assets_placeKey_itemKey_idx" ON "image_assets"("placeKey", "itemKey");

-- CreateIndex
CREATE INDEX "help_requests_ownerUserId_idx" ON "help_requests"("ownerUserId");

-- CreateIndex
CREATE INDEX "help_requests_status_answerCount_idx" ON "help_requests"("status", "answerCount");

-- CreateIndex
CREATE INDEX "help_requests_questionId_idx" ON "help_requests"("questionId");

-- CreateIndex
CREATE INDEX "help_answers_helpRequestId_idx" ON "help_answers"("helpRequestId");

-- CreateIndex
CREATE INDEX "help_answers_answerUserId_idx" ON "help_answers"("answerUserId");

-- CreateIndex
CREATE INDEX "pipi_runs_questionId_idx" ON "pipi_runs"("questionId");

-- CreateIndex
CREATE INDEX "pipi_runs_helpRequestId_idx" ON "pipi_runs"("helpRequestId");

-- CreateIndex
CREATE INDEX "pipi_runs_runType_status_idx" ON "pipi_runs"("runType", "status");

-- CreateIndex
CREATE INDEX "light_events_userId_litAt_idx" ON "light_events"("userId", "litAt");

-- CreateIndex
CREATE INDEX "light_events_type_idx" ON "light_events"("type");

-- AddForeignKey
ALTER TABLE "questions" ADD CONSTRAINT "questions_userId_fkey" FOREIGN KEY ("userId") REFERENCES "users"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "questions" ADD CONSTRAINT "questions_currentCardId_fkey" FOREIGN KEY ("currentCardId") REFERENCES "top1_cards"("id") ON DELETE SET NULL ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "questions" ADD CONSTRAINT "questions_helpRequestId_fkey" FOREIGN KEY ("helpRequestId") REFERENCES "help_requests"("id") ON DELETE SET NULL ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "top1_cards" ADD CONSTRAINT "top1_cards_questionId_fkey" FOREIGN KEY ("questionId") REFERENCES "questions"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "top1_cards" ADD CONSTRAINT "top1_cards_userId_fkey" FOREIGN KEY ("userId") REFERENCES "users"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "top1_cards" ADD CONSTRAINT "top1_cards_imageAssetId_fkey" FOREIGN KEY ("imageAssetId") REFERENCES "image_assets"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "help_requests" ADD CONSTRAINT "help_requests_questionId_fkey" FOREIGN KEY ("questionId") REFERENCES "questions"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "help_requests" ADD CONSTRAINT "help_requests_ownerUserId_fkey" FOREIGN KEY ("ownerUserId") REFERENCES "users"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "help_requests" ADD CONSTRAINT "help_requests_finalCardId_fkey" FOREIGN KEY ("finalCardId") REFERENCES "top1_cards"("id") ON DELETE SET NULL ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "help_answers" ADD CONSTRAINT "help_answers_helpRequestId_fkey" FOREIGN KEY ("helpRequestId") REFERENCES "help_requests"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "help_answers" ADD CONSTRAINT "help_answers_answerUserId_fkey" FOREIGN KEY ("answerUserId") REFERENCES "users"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "pipi_runs" ADD CONSTRAINT "pipi_runs_questionId_fkey" FOREIGN KEY ("questionId") REFERENCES "questions"("id") ON DELETE SET NULL ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "pipi_runs" ADD CONSTRAINT "pipi_runs_helpRequestId_fkey" FOREIGN KEY ("helpRequestId") REFERENCES "help_requests"("id") ON DELETE SET NULL ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "light_events" ADD CONSTRAINT "light_events_userId_fkey" FOREIGN KEY ("userId") REFERENCES "users"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "light_events" ADD CONSTRAINT "light_events_questionId_fkey" FOREIGN KEY ("questionId") REFERENCES "questions"("id") ON DELETE SET NULL ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "light_events" ADD CONSTRAINT "light_events_helpRequestId_fkey" FOREIGN KEY ("helpRequestId") REFERENCES "help_requests"("id") ON DELETE SET NULL ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "light_events" ADD CONSTRAINT "light_events_cardId_fkey" FOREIGN KEY ("cardId") REFERENCES "top1_cards"("id") ON DELETE SET NULL ON UPDATE CASCADE;
