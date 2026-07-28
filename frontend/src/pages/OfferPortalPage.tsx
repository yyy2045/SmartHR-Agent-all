import {
  CalendarOutlined,
  CheckCircleOutlined,
  CloseCircleOutlined,
  LockOutlined,
  ReloadOutlined,
  SafetyCertificateOutlined,
  SolutionOutlined,
} from '@ant-design/icons'
import { useMutation, useQuery } from '@tanstack/react-query'
import {
  Alert,
  Button,
  Descriptions,
  Divider,
  Form,
  Input,
  Modal,
  Result,
  Select,
  Skeleton,
  Tag,
  Typography,
  message,
} from 'antd'
import { useEffect, useRef, useState, type ReactNode } from 'react'

import {
  abandonPortalOnboarding,
  ApiError,
  confirmPortalOnboardingDate,
  fetchOfferPortalDetail,
  fetchOfferPortalStatus,
  proposePortalOnboardingDate,
  respondToOfferPortal,
  type CandidateOfferDecision,
  type CandidateOfferRejectionReason,
  type CandidateOfferViewRecord,
  type OnboardingAbandonmentReason,
  type OfferPortalVerifiedRecord,
  verifyOfferPortal,
} from '../api/client'

const { Title, Text, Paragraph } = Typography

interface VerificationValues {
  phoneLastFour: string
}

interface RejectionValues {
  reason: CandidateOfferRejectionReason
  note?: string
}

interface ResponseTarget {
  decision: CandidateOfferDecision
  idempotencyKey: string
}

interface OnboardingDateValues {
  date: string
  note: string
}

interface OnboardingAbandonValues {
  reason: OnboardingAbandonmentReason
  note: string
}

interface OnboardingTarget {
  kind: 'confirm' | 'propose' | 'abandon'
  idempotencyKey: string
}

const rejectionReasonLabels: Record<CandidateOfferRejectionReason, string> = {
  compensation: '薪资原因',
  career: '职业发展',
  location: '工作地点',
  timing: '入职时间',
  other: '其他原因',
}

const onboardingReasonLabels: Record<OnboardingAbandonmentReason, string> = {
  compensation: '薪酬原因',
  career: '职业发展',
  location: '工作地点',
  start_date: '入职日期',
  personal: '个人原因',
  position_cancelled: '职位取消',
  business_change: '业务调整',
  other: '其他原因',
}

function money(value: string | null) {
  if (value === null) return '不适用'
  return `${Number(value).toLocaleString('zh-CN', { maximumFractionDigits: 2 })} 元/月`
}

function formatDate(value: string | null) {
  if (!value) return '未确定'
  return new Intl.DateTimeFormat('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).format(new Date(`${value}T00:00:00`))
}

function formatDateTime(value: string) {
  return new Intl.DateTimeFormat('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }).format(new Date(value))
}

function annualSalary(offer: CandidateOfferViewRecord) {
  const total = Number(offer.monthly_salary) * Number(offer.annual_salary_months)
  return `${total.toLocaleString('zh-CN', { maximumFractionDigits: 2 })} 元/年`
}

function portalErrorContent(error: unknown) {
  if (!(error instanceof ApiError)) {
    return { title: '暂时无法打开页面', message: '请稍后重试', status: 'error' as const }
  }
  if (error.status === 404) {
    return { title: '链接无效', message: error.message, status: 'warning' as const }
  }
  if (error.status === 410) {
    return { title: '链接已失效', message: error.message, status: 'warning' as const }
  }
  if (error.status === 429) {
    return { title: '验证暂时锁定', message: error.message, status: 'warning' as const }
  }
  if (error.status === 503) {
    return { title: '验证服务暂不可用', message: error.message, status: 'error' as const }
  }
  return { title: '无法处理请求', message: error.message, status: 'error' as const }
}

function PortalShell({ children }: { children: ReactNode }) {
  return (
    <div className="candidate-offer-portal">
      <header className="candidate-offer-header">
        <div className="candidate-offer-brand">
          <span className="candidate-offer-brand-mark" aria-hidden="true">
            <SolutionOutlined />
          </span>
          <span>
            <Text strong>SmartHR</Text>
            <Text type="secondary">候选人服务</Text>
          </span>
        </div>
        <Text className="candidate-offer-security">
          <SafetyCertificateOutlined /> 安全访问
        </Text>
      </header>
      <main className="candidate-offer-main">{children}</main>
      <footer className="candidate-offer-footer">SmartHR 企业招聘平台</footer>
    </div>
  )
}

export function OfferPortalPage() {
  const capturedToken = useRef(false)
  const [verificationForm] = Form.useForm<VerificationValues>()
  const [rejectionForm] = Form.useForm<RejectionValues>()
  const [onboardingDateForm] = Form.useForm<OnboardingDateValues>()
  const [onboardingAbandonForm] = Form.useForm<OnboardingAbandonValues>()
  const [messageApi, messageContext] = message.useMessage()
  const [token, setToken] = useState('')
  const [tokenReady, setTokenReady] = useState(false)
  const [verification, setVerification] = useState<{
    token: string
    expiresAt: string
  }>()
  const [offer, setOffer] = useState<CandidateOfferViewRecord>()
  const [responseTarget, setResponseTarget] = useState<ResponseTarget>()
  const [onboardingTarget, setOnboardingTarget] = useState<OnboardingTarget>()
  const [terminalError, setTerminalError] = useState<unknown>()

  useEffect(() => {
    if (capturedToken.current) return
    capturedToken.current = true
    const fragment = window.location.hash.startsWith('#')
      ? window.location.hash.slice(1).trim()
      : ''
    window.history.replaceState(
      window.history.state,
      '',
      `${window.location.pathname}${window.location.search}`,
    )
    setToken(fragment)
    setTokenReady(true)
  }, [])

  const statusQuery = useQuery({
    queryKey: ['candidate-offer-portal-status'],
    queryFn: () => fetchOfferPortalStatus(token),
    enabled: tokenReady && Boolean(token),
    retry: false,
  })

  const verifyMutation = useMutation({
    mutationFn: (values: VerificationValues) =>
      verifyOfferPortal(token, values.phoneLastFour),
    onSuccess: (verified: OfferPortalVerifiedRecord) => {
      setVerification({
        token: verified.verification_token,
        expiresAt: verified.verification_expires_at,
      })
      setOffer(verified)
      setTerminalError(undefined)
    },
    onError: (error) => {
      if (error instanceof ApiError && [404, 410].includes(error.status)) {
        setTerminalError(error)
      }
    },
  })

  const responseMutation = useMutation({
    mutationFn: async ({
      target,
      rejection,
    }: {
      target: ResponseTarget
      rejection?: RejectionValues
    }) => {
      if (!verification) throw new Error('候选人验证已失效')
      return respondToOfferPortal(
        token,
        verification.token,
        target.decision,
        rejection?.reason ?? null,
        rejection?.note?.trim() || null,
        target.idempotencyKey,
      )
    },
    onSuccess: (saved, variables) => {
      setOffer(saved)
      if (variables.target.decision === 'rejected') rejectionForm.resetFields()
      setResponseTarget(undefined)
      void messageApi.success(saved.progress === 'accepted' ? '已接受 Offer' : '已提交拒绝回应')
    },
    onError: async (error) => {
      if (error instanceof ApiError && [404, 410].includes(error.status)) {
        setTerminalError(error)
        setResponseTarget(undefined)
        return
      }
      if (error instanceof ApiError && error.status === 401) {
        setOffer(undefined)
        setVerification(undefined)
        setResponseTarget(undefined)
        void messageApi.warning('身份验证已失效，请重新验证')
        return
      }
      if (error instanceof ApiError && error.status === 409 && verification) {
        try {
          const current = await fetchOfferPortalDetail(token, verification.token)
          setOffer(current)
          setResponseTarget(undefined)
          void messageApi.warning('Offer 状态已由其他操作更新')
        } catch {
          // Keep the original conflict visible in the confirmation dialog.
        }
      }
    },
  })

  const onboardingMutation = useMutation({
    mutationFn: async ({
      target,
      dateValues,
      abandonValues,
    }: {
      target: OnboardingTarget
      dateValues?: OnboardingDateValues
      abandonValues?: OnboardingAbandonValues
    }) => {
      if (!verification || !offer?.onboarding) throw new Error('候选人验证已失效')
      const onboarding = offer.onboarding
      if (target.kind === 'confirm') {
        return confirmPortalOnboardingDate(
          token,
          verification.token,
          onboarding.version,
          onboarding.recruiter_proposed_date ?? onboarding.expected_start_date,
          target.idempotencyKey,
        )
      }
      if (target.kind === 'propose') {
        return proposePortalOnboardingDate(
          token,
          verification.token,
          onboarding.version,
          dateValues!.date,
          dateValues!.note.trim(),
          target.idempotencyKey,
        )
      }
      return abandonPortalOnboarding(
        token,
        verification.token,
        onboarding.version,
        abandonValues!.reason,
        abandonValues!.note.trim(),
        target.idempotencyKey,
      )
    },
    onSuccess: (saved, variables) => {
      setOffer(saved)
      if (variables.target.kind === 'propose') onboardingDateForm.resetFields()
      if (variables.target.kind === 'abandon') onboardingAbandonForm.resetFields()
      setOnboardingTarget(undefined)
      const successMessage = variables.target.kind === 'confirm'
        ? '已确认入职日期'
        : variables.target.kind === 'propose'
          ? '已提交新的入职日期'
          : '已提交无法入职说明'
      void messageApi.success(successMessage)
    },
    onError: async (error) => {
      if (error instanceof ApiError && [404, 410].includes(error.status)) {
        setTerminalError(error)
        setOnboardingTarget(undefined)
        return
      }
      if (error instanceof ApiError && error.status === 401) {
        setOffer(undefined)
        setVerification(undefined)
        setOnboardingTarget(undefined)
        void messageApi.warning('身份验证已失效，请重新验证')
        return
      }
      if (error instanceof ApiError && error.status === 409 && verification) {
        try {
          const current = await fetchOfferPortalDetail(token, verification.token)
          setOffer(current)
          setOnboardingTarget(undefined)
          void messageApi.warning('入职状态已更新，请查看最新结果')
        } catch (refreshError) {
          if (refreshError instanceof ApiError && refreshError.status === 401) {
            setOffer(undefined)
            setVerification(undefined)
          }
        }
      }
    },
  })

  function openResponse(decision: CandidateOfferDecision) {
    setResponseTarget({ decision, idempotencyKey: crypto.randomUUID() })
  }

  function submitResponse() {
    if (!responseTarget) return
    if (responseTarget.decision === 'accepted') {
      responseMutation.mutate({ target: responseTarget })
      return
    }
    void rejectionForm.validateFields()
      .then((rejection) => {
        responseMutation.mutate({ target: responseTarget, rejection })
      })
      .catch(() => undefined)
  }

  function openOnboardingAction(kind: OnboardingTarget['kind']) {
    setOnboardingTarget({ kind, idempotencyKey: crypto.randomUUID() })
  }

  function submitOnboardingAction() {
    if (!onboardingTarget) return
    if (onboardingTarget.kind === 'confirm') {
      onboardingMutation.mutate({ target: onboardingTarget })
      return
    }
    if (onboardingTarget.kind === 'propose') {
      void onboardingDateForm.validateFields()
        .then((dateValues) => {
          onboardingMutation.mutate({ target: onboardingTarget, dateValues })
        })
        .catch(() => undefined)
      return
    }
    void onboardingAbandonForm.validateFields()
      .then((abandonValues) => {
        onboardingMutation.mutate({ target: onboardingTarget, abandonValues })
      })
      .catch(() => undefined)
  }

  if (!tokenReady) {
    return (
      <PortalShell>
        <section className="candidate-offer-panel">
          <Skeleton active paragraph={{ rows: 5 }} />
        </section>
      </PortalShell>
    )
  }

  if (!token) {
    return (
      <PortalShell>
        <section className="candidate-offer-panel">
          <Result status="warning" title="链接不完整" subTitle="请使用招聘专员提供的完整链接。" />
        </section>
      </PortalShell>
    )
  }

  const blockingError = terminalError ?? statusQuery.error
  if (blockingError) {
    const content = portalErrorContent(blockingError)
    return (
      <PortalShell>
        <section className="candidate-offer-panel">
          <Result
            status={content.status}
            title={content.title}
            subTitle={content.message}
            extra={
              blockingError instanceof ApiError && blockingError.status === 503 ? (
                <Button icon={<ReloadOutlined />} onClick={() => void statusQuery.refetch()}>
                  重新加载
                </Button>
              ) : undefined
            }
          />
        </section>
      </PortalShell>
    )
  }

  if (statusQuery.isPending || !statusQuery.data) {
    return (
      <PortalShell>
        <section className="candidate-offer-panel">
          <Skeleton active paragraph={{ rows: 6 }} />
        </section>
      </PortalShell>
    )
  }

  if (!offer || !verification) {
    const verifyError = verifyMutation.error
      ? portalErrorContent(verifyMutation.error)
      : undefined
    return (
      <PortalShell>
        {messageContext}
        <section className="candidate-offer-panel candidate-offer-verification" aria-labelledby="offer-verify-title">
          <span className="candidate-offer-lock" aria-hidden="true">
            <LockOutlined />
          </span>
          <Title level={2} id="offer-verify-title">验证身份</Title>
          <Text type="secondary">输入手机号码后四位</Text>
          {verifyError && (
            <Alert
              type={verifyMutation.error instanceof ApiError && verifyMutation.error.status === 503 ? 'error' : 'warning'}
              showIcon
              message={verifyError.title}
              description={verifyError.message}
            />
          )}
          <Form<VerificationValues>
            form={verificationForm}
            layout="vertical"
            requiredMark={false}
            onFinish={(values) => verifyMutation.mutate(values)}
          >
            <Form.Item
              label="手机号后四位"
              name="phoneLastFour"
              rules={[
                { required: true, message: '请输入手机号后四位' },
                { pattern: /^\d{4}$/, message: '请输入 4 位数字' },
              ]}
            >
              <Input
                size="large"
                inputMode="numeric"
                autoComplete="one-time-code"
                maxLength={4}
                placeholder="0000"
              />
            </Form.Item>
            <Button
              type="primary"
              size="large"
              htmlType="submit"
              loading={verifyMutation.isPending}
              block
            >
              验证并查看 Offer
            </Button>
          </Form>
        </section>
      </PortalShell>
    )
  }

  const response = offer.response
  return (
    <PortalShell>
      {messageContext}
      <section className="candidate-offer-panel candidate-offer-document" aria-labelledby="candidate-offer-title">
        <div className="candidate-offer-title-row">
          <div>
            <Text type="secondary">{offer.candidate_name || '候选人'}，您好</Text>
            <Title level={2} id="candidate-offer-title">{offer.job_title}</Title>
          </div>
          <Tag color={offer.progress === 'offer_pending_response' ? 'processing' : offer.progress === 'accepted' ? 'success' : 'error'}>
            {offer.progress === 'offer_pending_response'
              ? '待回应'
              : offer.progress === 'accepted'
                ? '已接受'
                : '已拒绝'}
          </Tag>
        </div>

        <Descriptions column={{ xs: 1, sm: 2 }} bordered size="small">
          <Descriptions.Item label="月薪">{money(offer.monthly_salary)}</Descriptions.Item>
          <Descriptions.Item label="年薪月数">{Number(offer.annual_salary_months)} 薪</Descriptions.Item>
          <Descriptions.Item label="参考年薪" span={{ xs: 1, sm: 2 }}>{annualSalary(offer)}</Descriptions.Item>
          <Descriptions.Item label="试用期">{offer.probation_months ? `${offer.probation_months} 个月` : '无'}</Descriptions.Item>
          <Descriptions.Item label="试用期月薪">{money(offer.probation_monthly_salary)}</Descriptions.Item>
          <Descriptions.Item label="Offer 有效期">{formatDate(offer.valid_until)}</Descriptions.Item>
          <Descriptions.Item label="预计入职日">{formatDate(offer.expected_start_date)}</Descriptions.Item>
          <Descriptions.Item label="奖金说明" span={{ xs: 1, sm: 2 }}>{offer.bonus_description || '未填写'}</Descriptions.Item>
          <Descriptions.Item label="Offer 备注" span={{ xs: 1, sm: 2 }}>{offer.notes || '未填写'}</Descriptions.Item>
        </Descriptions>

        {response ? (
          <div className={`candidate-offer-response candidate-offer-response--${response.decision}`}>
            {response.decision === 'accepted' ? <CheckCircleOutlined /> : <CloseCircleOutlined />}
            <div>
              <Title level={4}>{response.decision === 'accepted' ? '您已接受 Offer' : '您已拒绝 Offer'}</Title>
              <Text type="secondary">回应时间：{formatDateTime(response.responded_at)}</Text>
              {response.rejection_reason_code && (
                <Paragraph>拒绝原因：{rejectionReasonLabels[response.rejection_reason_code]}</Paragraph>
              )}
              {response.rejection_note && <Paragraph>补充说明：{response.rejection_note}</Paragraph>}
            </div>
          </div>
        ) : (
          <>
            <Divider />
            <div className="candidate-offer-actions">
              <Button size="large" danger onClick={() => openResponse('rejected')}>拒绝 Offer</Button>
              <Button size="large" type="primary" icon={<CheckCircleOutlined />} onClick={() => openResponse('accepted')}>接受 Offer</Button>
            </div>
          </>
        )}

        {response?.decision === 'accepted' && offer.onboarding && (
          <section className="candidate-onboarding" aria-labelledby="candidate-onboarding-title">
            <Divider />
            <div className="candidate-onboarding-heading">
              <div>
                <Text type="secondary">下一步</Text>
                <Title level={3} id="candidate-onboarding-title">入职确认</Title>
              </div>
              <Tag color={
                offer.onboarding.status === 'onboarded'
                  ? 'success'
                  : offer.onboarding.status === 'abandoned'
                    ? 'default'
                    : offer.onboarding.status === 'candidate_proposed_date'
                      ? 'warning'
                      : 'processing'
              }>
                {{
                  pending_confirmation: '待您确认',
                  candidate_proposed_date: '等待招聘方确认',
                  pending_start: '待入职',
                  onboarded: '已入职',
                  abandoned: '已放弃',
                }[offer.onboarding.status]}
              </Tag>
            </div>

            <Descriptions column={{ xs: 1, sm: 2 }} bordered size="small">
              <Descriptions.Item label="Offer 预计日期">
                {formatDate(offer.onboarding.expected_start_date)}
              </Descriptions.Item>
              <Descriptions.Item label="当前确认日期">
                {formatDate(
                  offer.onboarding.confirmed_start_date ??
                  offer.onboarding.recruiter_proposed_date ??
                  offer.onboarding.candidate_proposed_date ??
                  offer.onboarding.expected_start_date,
                )}
              </Descriptions.Item>
              {offer.onboarding.actual_start_date && (
                <Descriptions.Item label="实际入职日期" span={{ xs: 1, sm: 2 }}>
                  {formatDate(offer.onboarding.actual_start_date)}
                </Descriptions.Item>
              )}
            </Descriptions>

            {offer.onboarding.status === 'pending_confirmation' && (
              <div className="candidate-onboarding-action-panel">
                <div>
                  <Text strong>请确认入职日期</Text>
                  <Text type="secondary">
                    当前日期为 {formatDate(offer.onboarding.recruiter_proposed_date ?? offer.onboarding.expected_start_date)}
                  </Text>
                </div>
                <div className="candidate-onboarding-actions">
                  <Button onClick={() => openOnboardingAction('propose')}>提出其他日期</Button>
                  <Button
                    type="primary"
                    icon={<CalendarOutlined />}
                    onClick={() => openOnboardingAction('confirm')}
                  >
                    确认入职日期
                  </Button>
                </div>
              </div>
            )}

            {offer.onboarding.status === 'candidate_proposed_date' && (
              <Alert
                type="info"
                showIcon
                message="招聘专员正在确认您提出的日期"
                description={`您提出的日期：${formatDate(offer.onboarding.candidate_proposed_date)}`}
              />
            )}

            {offer.onboarding.status === 'pending_start' && (
              <Alert
                type="success"
                showIcon
                message="入职日期已确认"
                description={`确认日期：${formatDate(offer.onboarding.confirmed_start_date)}`}
              />
            )}

            {offer.onboarding.status === 'onboarded' && (
              <Alert
                type="success"
                showIcon
                message="已完成入职"
                description={`实际入职日期：${formatDate(offer.onboarding.actual_start_date)}`}
              />
            )}

            {offer.onboarding.status === 'abandoned' && (
              <Alert
                type="warning"
                showIcon
                message="入职流程已结束"
                description={offer.onboarding.abandonment_reason_code
                  ? `原因：${onboardingReasonLabels[offer.onboarding.abandonment_reason_code]}`
                  : undefined}
              />
            )}

            {['pending_confirmation', 'candidate_proposed_date', 'pending_start'].includes(offer.onboarding.status) && (
              <Button
                type="link"
                danger
                className="candidate-onboarding-abandon"
                onClick={() => openOnboardingAction('abandon')}
              >
                无法按计划入职
              </Button>
            )}
          </section>
        )}

        <Text type="secondary" className="candidate-offer-verification-expiry">
          身份验证有效至 {formatDateTime(verification.expiresAt)}
        </Text>
      </section>

      <Modal
        title={responseTarget?.decision === 'accepted' ? '确认接受 Offer' : '确认拒绝 Offer'}
        open={Boolean(responseTarget)}
        okText={responseTarget?.decision === 'accepted' ? '确认接受' : '确认拒绝'}
        cancelText="返回"
        okButtonProps={{ danger: responseTarget?.decision === 'rejected' }}
        confirmLoading={responseMutation.isPending}
        onOk={submitResponse}
        onCancel={() => {
          setResponseTarget(undefined)
          rejectionForm.resetFields()
          responseMutation.reset()
        }}
      >
        {responseMutation.error && (
          <Alert
            type="error"
            showIcon
            message={portalErrorContent(responseMutation.error).message}
          />
        )}
        {responseTarget?.decision === 'accepted' ? (
          <Paragraph>确认后回应不能修改。</Paragraph>
        ) : (
          <Form<RejectionValues> form={rejectionForm} layout="vertical">
            <Form.Item
              label="拒绝原因"
              name="reason"
              rules={[{ required: true, message: '请选择拒绝原因' }]}
            >
              <Select
                options={Object.entries(rejectionReasonLabels).map(([value, label]) => ({
                  value,
                  label,
                }))}
              />
            </Form.Item>
            <Form.Item label="补充说明" name="note">
              <Input.TextArea rows={4} maxLength={2_000} showCount />
            </Form.Item>
          </Form>
        )}
      </Modal>

      <Modal
        title={{
          confirm: '确认入职日期',
          propose: '提出其他入职日期',
          abandon: '确认无法入职',
        }[onboardingTarget?.kind ?? 'confirm']}
        open={Boolean(onboardingTarget)}
        okText={onboardingTarget?.kind === 'abandon' ? '确认放弃入职' : '确认提交'}
        cancelText="返回"
        okButtonProps={{ danger: onboardingTarget?.kind === 'abandon' }}
        confirmLoading={onboardingMutation.isPending}
        onOk={submitOnboardingAction}
        onCancel={() => {
          if (onboardingTarget?.kind === 'propose') onboardingDateForm.resetFields()
          if (onboardingTarget?.kind === 'abandon') onboardingAbandonForm.resetFields()
          setOnboardingTarget(undefined)
          onboardingMutation.reset()
        }}
      >
        {onboardingMutation.error && (
          <Alert
            type="error"
            showIcon
            message={portalErrorContent(onboardingMutation.error).message}
          />
        )}
        {onboardingTarget?.kind === 'confirm' && offer.onboarding && (
          <Paragraph>
            确认后，入职日期为{' '}
            {formatDate(offer.onboarding.recruiter_proposed_date ?? offer.onboarding.expected_start_date)}。
          </Paragraph>
        )}
        {onboardingTarget?.kind === 'propose' && (
          <Form<OnboardingDateValues> form={onboardingDateForm} layout="vertical" requiredMark={false}>
            <Form.Item label="其他入职日期" name="date" rules={[{ required: true, message: '请选择日期' }]}>
              <Input type="date" />
            </Form.Item>
            <Form.Item label="调整说明" name="note" rules={[{ required: true, message: '请填写说明' }]}>
              <Input.TextArea rows={3} maxLength={2_000} showCount />
            </Form.Item>
          </Form>
        )}
        {onboardingTarget?.kind === 'abandon' && (
          <Form<OnboardingAbandonValues>
            form={onboardingAbandonForm}
            layout="vertical"
            initialValues={{ reason: 'personal', note: '' }}
            requiredMark={false}
          >
            <Form.Item label="原因分类" name="reason" rules={[{ required: true, message: '请选择原因' }]}>
              <Select
                options={Object.entries(onboardingReasonLabels).map(([value, label]) => ({ value, label }))}
              />
            </Form.Item>
            <Form.Item label="详细说明" name="note" rules={[{ required: true, message: '请填写说明' }]}>
              <Input.TextArea rows={3} maxLength={2_000} showCount />
            </Form.Item>
          </Form>
        )}
      </Modal>
    </PortalShell>
  )
}
